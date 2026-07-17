"""Post-agent validation against the authoritative deterministic result."""

from __future__ import annotations

from ncs_collector.models import (
    QualificationEvidence,
    RequirementEvidenceResult,
    SpecGapReport,
    StructuredGapAnalysis,
)
from ncs_collector.text import comparison_key
from spec_report.qnet import validate_qnet_url


class ReportValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


_AUTHORITATIVE_FIELDS = (
    "target_trade",
    "target_specialty",
    "analysis_scope",
    "normalized_certifications",
    "satisfied_certification_groups",
    "missing_core_certification_groups",
    "recommended_certification_groups",
    "ability_coverage",
    "matched_abilities",
    "missing_abilities",
    "priority_actions",
)


def _qualification_payload(item: QualificationEvidence) -> dict:
    payload = item.model_dump(mode="json")
    payload.pop("from_cache", None)
    return payload


def validate_report(
    report: SpecGapReport,
    structured: StructuredGapAnalysis,
    kb_results: dict[str, RequirementEvidenceResult] | None = None,
    qnet_results: dict[str, QualificationEvidence] | None = None,
    evidence_plan: list[dict] | None = None,
) -> None:
    errors: list[str] = []
    for field in _AUTHORITATIVE_FIELDS:
        if getattr(report, field) != getattr(structured, field):
            errors.append(f"authoritative field changed: {field}")

    satisfied = {comparison_key(item.group_name) for item in structured.satisfied_certification_groups}
    missing = {comparison_key(item.group_name) for item in report.missing_core_certification_groups}
    if satisfied & missing:
        errors.append("a satisfied certification group was reported as missing")

    allowed_names = {comparison_key(structured.target_trade)}
    for item in structured.normalized_certifications:
        allowed_names.add(comparison_key(item.input_name))
        if item.normalized_name:
            allowed_names.add(comparison_key(item.normalized_name))
    for group in (
        structured.satisfied_certification_groups
        + structured.missing_core_certification_groups
        + structured.recommended_certification_groups
    ):
        allowed_names.add(comparison_key(group.group_name))
        allowed_names.update(comparison_key(name) for name in group.certification_names)
    for ability in structured.matched_abilities + structured.missing_abilities:
        allowed_names.add(comparison_key(ability.ability_name))
        allowed_names.add(comparison_key(ability.ncs_code))

    planned_kb = {
        comparison_key(item["itemName"]): item
        for item in (evidence_plan or []) if item.get("action") == "KB"
    }
    planned_qnet = {
        comparison_key(item["itemName"]): item
        for item in (evidence_plan or []) if item.get("action") == "QNET"
    }
    expected_kb = {
        comparison_key(name): value for name, value in (kb_results or {}).items()
    }
    expected_qnet = {
        comparison_key(name): value for name, value in (qnet_results or {}).items()
    }

    for item in report.knowledge_base_evidence:
        item_key = comparison_key(item.item_name)
        if comparison_key(item.item_name) not in allowed_names:
            errors.append(f"invented evidence item: {item.item_name}")
        if evidence_plan is not None and item_key not in planned_kb:
            errors.append(f"KB evidence item is not in evidence plan: {item.item_name}")
        planned = planned_kb.get(item_key)
        if planned and item.item_type != planned.get("itemType"):
            errors.append(f"KB evidence item type differs from plan: {item.item_name}")
        if item.decision != "AUTHORITATIVE_RESULT_UNCHANGED":
            errors.append(f"KB evidence attempted to restate a decision: {item.item_name}")
        if item.qnet_official_url or item.qnet_checked_at:
            errors.append(f"KB evidence contains non-authoritative Q-Net fields: {item.item_name}")
        if kb_results is not None:
            expected = expected_kb.get(item_key)
            if expected is None:
                errors.append(f"KB evidence was not retrieved: {item.item_name}")
            else:
                allowed_ids = {evidence.document_id for evidence in expected.evidence if evidence.document_id}
                if not set(item.local_document_ids) <= allowed_ids:
                    errors.append(f"KB evidence contains unreturned document id: {item.item_name}")
                allowed_ncs = {
                    str(code)
                    for evidence in expected.evidence
                    if (code := evidence.metadata.get("ncs_code") or evidence.metadata.get("NCS코드"))
                }
                if not set(item.ncs_codes) <= allowed_ncs:
                    errors.append(f"KB evidence contains unreturned NCS code: {item.item_name}")
                allowed_types = {str(evidence.evidence_type) for evidence in expected.evidence}
                if not set(item.evidence_types) <= allowed_types:
                    errors.append(f"KB evidence contains unreturned evidence type: {item.item_name}")
    for item in report.qnet_evidence:
        item_key = comparison_key(item.normalized_name)
        if item_key not in allowed_names:
            errors.append(f"invented Q-Net qualification: {item.normalized_name}")
        if evidence_plan is not None and item_key not in planned_qnet:
            errors.append(f"Q-Net evidence item is not in evidence plan: {item.normalized_name}")
        if item.fetch_status == "SUCCESS" and (not item.source_url or not item.checked_at):
            errors.append(f"official Q-Net claim lacks URL/time: {item.normalized_name}")
        if item.fetch_status == "SUCCESS" and item.source_url:
            try:
                validate_qnet_url(item.source_url)
            except ValueError:
                errors.append(f"official Q-Net claim has non-official URL: {item.normalized_name}")
        if qnet_results is not None:
            expected = expected_qnet.get(item_key)
            if expected is None:
                errors.append(f"Q-Net evidence was not fetched: {item.normalized_name}")
            elif _qualification_payload(item) != _qualification_payload(expected):
                errors.append(f"Q-Net evidence differs from fetched result: {item.normalized_name}")

    report_citations = {
        (
            comparison_key(citation.item_name),
            str(citation.source_type),
            citation.document_id,
            citation.source_url,
            citation.checked_at,
        )
        for citation in report.citations
    }
    for citation in report.citations:
        if citation.source_type in {"BEDROCK_KB", "LOCAL_KEYWORD"} and not (citation.document_id or citation.source_url):
            errors.append(f"KB/local citation lacks document id/location: {citation.item_name}")
        citation_key = comparison_key(citation.item_name)
        if citation.source_type in {"BEDROCK_KB", "LOCAL_KEYWORD"} and kb_results is not None:
            expected = expected_kb.get(citation_key)
            matches = expected and any(
                str(evidence.evidence_type) == citation.source_type
                and evidence.document_id == citation.document_id
                and evidence.source_location == citation.source_url
                for evidence in expected.evidence
            )
            if not matches:
                errors.append(f"KB/local citation was not returned by retrieval: {citation.item_name}")
        if citation.source_type == "QNET" and qnet_results is not None:
            expected = expected_qnet.get(citation_key)
            if not expected or (
                expected.source_url != citation.source_url
                or expected.checked_at != citation.checked_at
            ):
                errors.append(f"Q-Net citation differs from fetched result: {citation.item_name}")

    if kb_results is not None:
        for item_name, expected in kb_results.items():
            if expected.evidence and not any(
                comparison_key(citation[0]) == comparison_key(item_name)
                and citation[1] in {"BEDROCK_KB", "LOCAL_KEYWORD"}
                for citation in report_citations
            ):
                errors.append(f"retrieved KB evidence lacks a citation: {item_name}")
            if (expected.status != "SUCCESS" or not expected.evidence) and not any(
                item_name in review for review in report.human_review_items
            ):
                errors.append(f"unconfirmed KB evidence lacks human review item: {item_name}")
    if qnet_results is not None:
        for item_name, expected in qnet_results.items():
            if expected.source_url and not any(
                citation[0] == comparison_key(item_name)
                and citation[1] == "QNET"
                and citation[3] == expected.source_url
                and citation[4] == expected.checked_at
                for citation in report_citations
            ):
                errors.append(f"fetched Q-Net evidence lacks a citation: {item_name}")
            if expected.fetch_status != "SUCCESS" and not any(
                item_name in review for review in report.human_review_items
            ):
                errors.append(f"unconfirmed Q-Net evidence lacks human review item: {item_name}")

    mismatch_names = {item.normalized_name for item in report.qnet_evidence if item.fetch_status == "NAME_MISMATCH"}
    if mismatch_names and not any(any(name in review for name in mismatch_names) for review in report.human_review_items):
        errors.append("Q-Net name mismatch is not recorded for human review")
    if errors:
        raise ReportValidationError(errors)


def missing_evidence_items(report: SpecGapReport, evidence_plan: list[dict]) -> list[dict]:
    cited = {comparison_key(item.item_name) for item in report.knowledge_base_evidence}
    qnet = {comparison_key(item.normalized_name) for item in report.qnet_evidence}
    missing: list[dict] = []
    for item in evidence_plan:
        name = comparison_key(item["itemName"])
        if item["action"] == "KB" and name not in cited:
            missing.append(item)
        if item["action"] == "QNET" and name not in qnet:
            missing.append(item)
    return missing
