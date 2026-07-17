#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
STAGE="${STAGE:-dev}"
STACK_NAME="${STACK_NAME:-crewmate}"
STATE_DIR="${STATE_DIR:-${REPO_ROOT}/.aws-kb}"
STATE_FILE="${STATE_FILE:-${STATE_DIR}/${STAGE}.json}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "required command not found: $1" >&2
    exit 1
  }
}

require_command aws
require_command jq
mkdir -p "${STATE_DIR}"

account_id() {
  aws sts get-caller-identity --query Account --output text --region "${AWS_REGION}"
}

stack_output() {
  local key="$1"
  aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --region "${AWS_REGION}" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue | [0]" \
    --output text
}

state_value() {
  local key="$1"
  [[ -f "${STATE_FILE}" ]] || return 1
  jq -er ".${key}" "${STATE_FILE}"
}

wait_for_kb() {
  local kb_id="$1"
  for _ in $(seq 1 60); do
    local status
    status="$(aws bedrock-agent get-knowledge-base --knowledge-base-id "${kb_id}" --region "${AWS_REGION}" --query 'knowledgeBase.status' --output text)"
    case "${status}" in
      ACTIVE|AVAILABLE) return 0 ;;
      FAILED|DELETE_UNSUCCESSFUL) echo "knowledge base failed: ${status}" >&2; return 1 ;;
    esac
    sleep 5
  done
  echo "timed out waiting for knowledge base ${kb_id}" >&2
  return 1
}

wait_for_data_source() {
  local kb_id="$1" data_source_id="$2"
  for _ in $(seq 1 60); do
    local status
    status="$(aws bedrock-agent get-data-source --knowledge-base-id "${kb_id}" --data-source-id "${data_source_id}" --region "${AWS_REGION}" --query 'dataSource.status' --output text)"
    case "${status}" in
      ACTIVE|AVAILABLE) return 0 ;;
      FAILED|DELETE_UNSUCCESSFUL) echo "data source failed: ${status}" >&2; return 1 ;;
    esac
    sleep 5
  done
  echo "timed out waiting for data source ${data_source_id}" >&2
  return 1
}

wait_for_ingestion() {
  local kb_id="$1" data_source_id="$2" ingestion_id="$3"
  for _ in $(seq 1 120); do
    local status
    status="$(aws bedrock-agent get-ingestion-job --knowledge-base-id "${kb_id}" --data-source-id "${data_source_id}" --ingestion-job-id "${ingestion_id}" --region "${AWS_REGION}" --query 'ingestionJob.status' --output text)"
    case "${status}" in
      COMPLETE) return 0 ;;
      FAILED|STOPPED)
        aws bedrock-agent get-ingestion-job --knowledge-base-id "${kb_id}" --data-source-id "${data_source_id}" --ingestion-job-id "${ingestion_id}" --region "${AWS_REGION}" --output json >&2
        return 1
        ;;
    esac
    sleep 5
  done
  echo "timed out waiting for ingestion ${ingestion_id}" >&2
  return 1
}
