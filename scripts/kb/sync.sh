#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"
require_command uv

SOURCE_BUCKET="${KNOWLEDGE_SOURCE_BUCKET:-$(state_value sourceBucket)}"
KB_ID="${KNOWLEDGE_BASE_ID:-$(state_value knowledgeBaseId)}"
DATA_SOURCE_ID="${KNOWLEDGE_BASE_DATA_SOURCE_ID:-$(state_value dataSourceId)}"

cd "${REPO_ROOT}"
UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/kiro-uv-cache}" uv run --isolated --python 3.12 \
  --with-requirements requirements.txt python main.py build-rag \
  --source-root Archive --output-root data/rag-ready >/dev/null

aws s3 sync data/rag-ready/rules "s3://${SOURCE_BUCKET}/rules" --delete --region "${AWS_REGION}"
aws s3 sync data/rag-ready/knowledge-base "s3://${SOURCE_BUCKET}/knowledge-base" --delete --region "${AWS_REGION}"

INGESTION_ID="$(aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "${KB_ID}" \
  --data-source-id "${DATA_SOURCE_ID}" \
  --description "CrewMate ${STAGE} structured evidence sync" \
  --region "${AWS_REGION}" \
  --query 'ingestionJob.ingestionJobId' --output text)"
wait_for_ingestion "${KB_ID}" "${DATA_SOURCE_ID}" "${INGESTION_ID}"
INGESTION_RESULT="$(aws bedrock-agent get-ingestion-job \
  --knowledge-base-id "${KB_ID}" \
  --data-source-id "${DATA_SOURCE_ID}" \
  --ingestion-job-id "${INGESTION_ID}" \
  --region "${AWS_REGION}" \
  --output json)"
if ! jq -e '
  ((.ingestionJob.failureReasons // []) | length) == 0 and
  ((.ingestionJob.statistics.numberOfDocumentsFailed // 0) == 0)
' <<<"${INGESTION_RESULT}" >/dev/null; then
  echo "ingestion completed with failures" >&2
  jq '.ingestionJob | {status,statistics,failureReasons}' <<<"${INGESTION_RESULT}" >&2
  exit 1
fi
echo "Ingestion complete: ${INGESTION_ID}"
