"""Application orchestration: rules -> evidence plan -> agent -> validation -> fallback."""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from ncs_collector.gap_analyzer import analyze_gap
from ncs_collector.models import (
    ApplicantSpecInput,
    QualificationEvidence,
    RequirementEvidenceResult,
    SpecGapReport,
    StructuredGapAnalysis,
)
from ncs_collector.trade_requirements import RuleRepository
from spec_report.qnet import QNetQualificationService
from spec_report.rendering import build_fallback_report, materialize_agent_report, render_markdown
from spec_report.report_agent import ReportAgentRunner, ReportAgentUnavailable
from spec_report.retrieval import RequirementRetriever
from spec_report.validator import ReportValidationError, missing_evidence_items, validate_report

logger = logging.getLogger(__name__)


class ReportStorage(Protocol):
    def save(self, report: SpecGapReport, markdown: str | None) -> dict[str, str]: ...


def build_evidence_plan(
    structured: StructuredGapAnalysis,
    repository: RuleRepository,
    *,
    include_qnet: bool = True,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for group in structured.missing_core_certification_groups + structured.recommended_certification_groups:
        if group.satisfied:
            continue
        plan.append({
            "action": "KB",
            "targetTrade": structured.target_trade,
            "itemName": group.group_name,
            "itemType": "CERTIFICATION",
            "query": f"{structured.target_trade} {group.group_name} 자격 요건 근거",
            "documentTypes": ["직종 자격·능력 요약", "자격 요건"],
        })
    for ability in structured.missing_abilities:
        plan.append({
            "action": "KB",
            "targetTrade": structured.target_trade,
            "itemName": ability.ability_name,
            "itemType": "ABILITY",
            "ncsCode": ability.ncs_code,
            "query": f"{structured.target_trade} {ability.ability_name} {ability.ncs_code} NCS 능력 근거",
            "documentTypes": ["NCS 능력 요구사항"],
        })
    if include_qnet:
        targets: list[str] = []
        targets.extend(
            item.normalized_name
            for item in structured.normalized_certifications
            if item.matched and item.normalized_name
        )
        for group in structured.missing_core_certification_groups + structured.recommended_certification_groups:
            if not group.satisfied:
                targets.extend(group.certification_names)
        normalizer = repository.certification_normalizer()
        for name in dict.fromkeys(targets):
            metadata = normalizer.normalize(name)
            plan.append({
                "action": "QNET",
                "targetTrade": structured.target_trade,
                "itemName": name,
                "itemType": "CERTIFICATION",
                "qnetUrl": metadata.qnet_url or "",
            })
    return plan


def _serialize_evidence(
    kb_results: dict[str, RequirementEvidenceResult],
    qnet_results: dict[str, QualificationEvidence],
) -> dict[str, Any]:
    return {
        "knowledgeBase": {key: value.model_dump(mode="json", by_alias=True) for key, value in kb_results.items()},
        "qnet": {key: value.model_dump(mode="json", by_alias=True) for key, value in qnet_results.items()},
    }


class SpecReportService:
    def __init__(
        self,
        repository: RuleRepository,
        retriever: RequirementRetriever,
        qnet_service: QNetQualificationService,
        *,
        agent_runner: ReportAgentRunner | None = None,
        storage: ReportStorage | None = None,
    ):
        self.repository = repository
        self.retriever = retriever
        self.qnet_service = qnet_service
        self.agent_runner = agent_runner
        self.storage = storage

    def _collect(
        self,
        structured: StructuredGapAnalysis,
        plan: list[dict[str, Any]],
        *,
        refresh_qnet: bool,
    ) -> tuple[dict[str, RequirementEvidenceResult], dict[str, QualificationEvidence]]:
        kb_results: dict[str, RequirementEvidenceResult] = {}
        qnet_results: dict[str, QualificationEvidence] = {}
        for item in plan:
            if item["action"] == "KB":
                kb_results[item["itemName"]] = self.retriever.retrieve_requirement_evidence(
                    target_trade=structured.target_trade,
                    query=item["query"],
                    item_type=item.get("itemType"),
                    item_name=item["itemName"],
                    ncs_code=item.get("ncsCode"),
                    document_types=item.get("documentTypes"),
                )
            elif item["action"] == "QNET":
                qnet_results[item["itemName"]] = self.qnet_service.fetch_qnet_qualification(
                    item["itemName"], item.get("qnetUrl", ""), force_refresh=refresh_qnet
                )
        return kb_results, qnet_results

    def generate(
        self,
        applicant: ApplicantSpecInput,
        *,
        offline: bool = False,
        refresh_qnet: bool = False,
        json_only: bool = False,
        report_id: str | None = None,
    ) -> tuple[SpecGapReport, str | None, dict[str, str]]:
        started = time.monotonic()
        structured = analyze_gap(applicant, self.repository)
        plan = build_evidence_plan(structured, self.repository, include_qnet=not offline)
        report: SpecGapReport | None = None
        first_error: str | None = None
        kb_results: dict[str, RequirementEvidenceResult] = {}
        qnet_results: dict[str, QualificationEvidence] = {}
        retry_allowed = True

        # First pass must obtain evidence through plan-bound Strands tools. Claims are
        # validated only against evidence actually observed from those calls.
        if not offline and self.agent_runner is not None:
            try:
                draft = self.agent_runner.run(structured, plan)
                kb_results.update(self.agent_runner.last_kb_results)
                qnet_results.update(self.agent_runner.last_qnet_results)
                candidate = materialize_agent_report(
                    structured, draft, kb_results, qnet_results
                )
                validate_report(candidate, structured, kb_results, qnet_results, plan)
                missing = missing_evidence_items(candidate, plan)
                if missing:
                    raise ReportValidationError([
                        "agent omitted planned evidence: "
                        + ", ".join(item["itemName"] for item in missing)
                    ])
                report = candidate
            except ReportAgentUnavailable as exc:
                kb_results.update(self.agent_runner.last_kb_results)
                qnet_results.update(self.agent_runner.last_qnet_results)
                first_error = str(exc)
                retry_allowed = False
                logger.warning("spec_report_agent_attempt_failed attempt=1 reason=%s", first_error)
            except ReportValidationError as exc:
                kb_results.update(self.agent_runner.last_kb_results)
                qnet_results.update(self.agent_runner.last_qnet_results)
                first_error = str(exc)
                logger.warning("spec_report_agent_attempt_failed attempt=1 reason=%s", first_error)

        pending_plan = [
            item for item in plan
            if (
                item["action"] == "KB" and item["itemName"] not in kb_results
            ) or (
                item["action"] == "QNET" and item["itemName"] not in qnet_results
            )
        ]
        collected_kb, collected_qnet = self._collect(
            structured, pending_plan, refresh_qnet=refresh_qnet
        )
        kb_results.update(collected_kb)
        qnet_results.update(collected_qnet)

        # One bounded retry with deterministically collected missing evidence; never loop.
        if report is None and retry_allowed and not offline and self.agent_runner is not None:
            try:
                draft = self.agent_runner.run(
                    structured, plan, _serialize_evidence(kb_results, qnet_results)
                )
                kb_results.update(self.agent_runner.last_kb_results)
                qnet_results.update(self.agent_runner.last_qnet_results)
                candidate = materialize_agent_report(
                    structured, draft, kb_results, qnet_results
                )
                validate_report(candidate, structured, kb_results, qnet_results, plan)
                missing = missing_evidence_items(candidate, plan)
                if missing:
                    raise ReportValidationError([
                        "agent retry omitted planned evidence: "
                        + ", ".join(item["itemName"] for item in missing)
                    ])
                report = candidate
            except (ReportAgentUnavailable, ReportValidationError) as exc:
                first_error = first_error or str(exc)
                logger.warning("spec_report_agent_attempt_failed attempt=2 reason=%s", str(exc))

        if report is None:
            extras = ["LLM 보고서 작성 실패로 구조화 결과 기반 보고서를 생성했다."] if first_error else []
            report = build_fallback_report(structured, kb_results, qnet_results, extra_limitations=extras)
        if report_id:
            report.report_id = report_id
        validate_report(report, structured, kb_results, qnet_results, plan)

        markdown = None if json_only else render_markdown(report)
        stored: dict[str, str] = {}
        if applicant.persist_report:
            if self.storage is None:
                report.limitations.append("persistReport가 요청되었으나 Report Storage가 구성되지 않았다.")
                report.human_review_items.append("보고서 저장 구성 확인 필요")
            else:
                stored = self.storage.save(report, markdown)

        logger.info(
            "spec_report_complete report_id=%s target_trade=%s analysis_scope=%s kb_items=%d qnet_items=%d agent_ms=%d validation=success persisted=%s",
            report.report_id,
            structured.target_trade,
            structured.analysis_scope,
            len(kb_results),
            len(qnet_results),
            int((time.monotonic() - started) * 1000),
            bool(stored),
        )
        return report, markdown, stored
