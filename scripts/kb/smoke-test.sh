#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

KB_ID="${KNOWLEDGE_BASE_ID:-$(state_value knowledgeBaseId)}"
RESULT_FILE="${RESULT_FILE:-/tmp/crewmate-kb-retrieve.json}"
FILTER='{"andAll":[{"equals":{"key":"trade","value":"방수시공"}},{"equals":{"key":"review_status","value":"구조화원본"}},{"equals":{"key":"document_type","value":"자격 요건"}}]}'
RETRIEVAL_CONFIG="$(jq -n --argjson filter "${FILTER}" '{vectorSearchConfiguration:{numberOfResults:5,filter:$filter}}')"

aws bedrock-agent-runtime retrieve \
  --knowledge-base-id "${KB_ID}" \
  --retrieval-query '{"text":"방수시공 방수 직접 자격 근거"}' \
  --retrieval-configuration "${RETRIEVAL_CONFIG}" \
  --region "${AWS_REGION}" \
  --output json > "${RESULT_FILE}"

jq -e '
  (.retrievalResults | length) > 0 and
  all(.retrievalResults[];
    .metadata.trade == "방수시공" and
    .metadata.review_status == "구조화원본" and
    (.metadata.document_id | length) > 0)
' "${RESULT_FILE}" >/dev/null

echo "Retrieve smoke test passed: ${RESULT_FILE}"
jq '{count:(.retrievalResults|length),results:[.retrievalResults[]|{score,documentId:.metadata.document_id,source:.location}]}' "${RESULT_FILE}"
