#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

KB_ID="${KNOWLEDGE_BASE_ID:-$(state_value knowledgeBaseId)}"
DATA_SOURCE_ID="${KNOWLEDGE_BASE_DATA_SOURCE_ID:-$(state_value dataSourceId)}"

aws bedrock-agent get-knowledge-base \
  --knowledge-base-id "${KB_ID}" \
  --region "${AWS_REGION}" \
  --query 'knowledgeBase.{id:knowledgeBaseId,name:name,status:status,storage:storageConfiguration.type}'

aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id "${KB_ID}" \
  --data-source-id "${DATA_SOURCE_ID}" \
  --region "${AWS_REGION}" \
  --max-results 5 \
  --query 'ingestionJobSummaries[].{id:ingestionJobId,status:status,startedAt:startedAt,updatedAt:updatedAt,statistics:statistics}'
