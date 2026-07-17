#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_command sam
REPORT_MODEL_ID="${REPORT_MODEL_ID:-global.anthropic.claude-sonnet-4-6}"
REPORT_FOUNDATION_MODEL_ID="${REPORT_FOUNDATION_MODEL_ID:-${REPORT_MODEL_ID#*.}}"

# Fail before CloudFormation changes if the configured system inference profile
# does not exist in this account/region.
aws bedrock get-inference-profile \
  --inference-profile-identifier "${REPORT_MODEL_ID}" \
  --region "${AWS_REGION}" >/dev/null

cd "${REPO_ROOT}"
export SAM_CLI_TELEMETRY=0
if command -v python3.13 >/dev/null 2>&1; then
  sam build --template-file template.yaml
else
  sam build --template-file template.yaml --use-container
fi

deploy_stack() {
  local kb_id="$1"
  local parameters=(
    Stage="${STAGE}"
    KnowledgeBaseRegion="${AWS_REGION}"
    KbReviewStatus="구조화원본"
    ReportModelId="${REPORT_MODEL_ID}"
    ReportFoundationModelId="${REPORT_FOUNDATION_MODEL_ID}"
  )
  if [[ -n "${kb_id}" ]]; then
    parameters+=(KnowledgeBaseId="${kb_id}")
  fi
  sam deploy \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --resolve-s3 \
    --capabilities CAPABILITY_IAM \
    --no-confirm-changeset \
    --no-fail-on-empty-changeset \
    --parameter-overrides "${parameters[@]}"
}

# Bootstrap the SAM-owned source bucket, report bucket, cache, and Lambda.
EXISTING_KB_ID="$(state_value knowledgeBaseId 2>/dev/null || stack_output ExternalKnowledgeBaseId 2>/dev/null || true)"
if [[ "${EXISTING_KB_ID}" == "None" ]]; then
  EXISTING_KB_ID=""
fi
deploy_stack "${EXISTING_KB_ID}"
SOURCE_BUCKET="$(stack_output KnowledgeSourceBucketName)"
KNOWLEDGE_SOURCE_BUCKET="${SOURCE_BUCKET}" "${SCRIPT_DIR}/provision.sh"
"${SCRIPT_DIR}/sync.sh"
"${SCRIPT_DIR}/smoke-test.sh"

# Wire the verified external KB ID into the report Lambda.
KB_ID="$(state_value knowledgeBaseId)"
deploy_stack "${KB_ID}"
echo "CrewMate spec-report stack and Knowledge Base deployed: ${KB_ID}"
