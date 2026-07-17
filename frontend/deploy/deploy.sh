#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUCKET="${FRONTEND_BUCKET:-crewmate-frontend-465105354705}"
DISTRIBUTION_ID="${CLOUDFRONT_DISTRIBUTION_ID:-E3C8JMPJGD7Z3Q}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"

for command_name in npm aws; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is missing: ${command_name}" >&2
    exit 1
  fi
done

cd "${FRONTEND_DIR}"
npm run build

aws s3 sync dist/ "s3://${BUCKET}" --delete --region "${AWS_REGION}"
aws s3 cp dist/index.html "s3://${BUCKET}/index.html" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --content-type "text/html" \
  --region "${AWS_REGION}"

INVALIDATION_ID="$(aws cloudfront create-invalidation \
  --distribution-id "${DISTRIBUTION_ID}" \
  --paths '/*' \
  --query 'Invalidation.Id' \
  --output text)"
aws cloudfront wait invalidation-completed \
  --distribution-id "${DISTRIBUTION_ID}" \
  --id "${INVALIDATION_ID}"

aws s3api head-object \
  --bucket "${BUCKET}" \
  --key index.html \
  --region "${AWS_REGION}" \
  --query '{ContentType:ContentType,CacheControl:CacheControl,Size:ContentLength}'

echo "Frontend deployed: https://d1872k8ivu18th.cloudfront.net"
