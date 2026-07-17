#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

ACCOUNT_ID="$(account_id)"
SOURCE_BUCKET="${KNOWLEDGE_SOURCE_BUCKET:-${1:-}}"
if [[ -z "${SOURCE_BUCKET}" ]]; then
  SOURCE_BUCKET="$(stack_output KnowledgeSourceBucketName)"
fi
if [[ -z "${SOURCE_BUCKET}" || "${SOURCE_BUCKET}" == "None" ]]; then
  echo "Knowledge Source bucket is required. Deploy the SAM stack first or set KNOWLEDGE_SOURCE_BUCKET." >&2
  exit 1
fi

VECTOR_BUCKET_NAME="${VECTOR_BUCKET_NAME:-crewmate-spec-kb-${ACCOUNT_ID}-${AWS_REGION}-${STAGE}}"
VECTOR_INDEX_NAME="${VECTOR_INDEX_NAME:-spec-gap-${STAGE}}"
ROLE_NAME="${KB_ROLE_NAME:-CrewMateBedrockKnowledgeBaseRole-${STAGE}}"
KB_NAME="${KB_NAME:-crewmate-spec-gap-${STAGE}}"
DATA_SOURCE_NAME="${KB_DATA_SOURCE_NAME:-crewmate-spec-gap-s3-${STAGE}}"
EMBEDDING_MODEL_ID="${EMBEDDING_MODEL_ID:-amazon.titan-embed-text-v2:0}"
EMBEDDING_DIMENSIONS="${EMBEDDING_DIMENSIONS:-1024}"
EMBEDDING_MODEL_ARN="arn:aws:bedrock:${AWS_REGION}::foundation-model/${EMBEDDING_MODEL_ID}"
VECTOR_BUCKET_ARN="arn:aws:s3vectors:${AWS_REGION}:${ACCOUNT_ID}:bucket/${VECTOR_BUCKET_NAME}"
VECTOR_INDEX_ARN="${VECTOR_BUCKET_ARN}/index/${VECTOR_INDEX_NAME}"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
ROLE_CREATED=false

if ! aws s3vectors get-vector-bucket --vector-bucket-name "${VECTOR_BUCKET_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1; then
  aws s3vectors create-vector-bucket \
    --vector-bucket-name "${VECTOR_BUCKET_NAME}" \
    --encryption-configuration '{"sseType":"AES256"}' \
    --tags "Project=CrewMate,Stage=${STAGE},Purpose=SpecGapKnowledgeBase" \
    --region "${AWS_REGION}" >/dev/null
fi

if ! aws s3vectors get-index --vector-bucket-name "${VECTOR_BUCKET_NAME}" --index-name "${VECTOR_INDEX_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1; then
  aws s3vectors create-index \
    --vector-bucket-name "${VECTOR_BUCKET_NAME}" \
    --index-name "${VECTOR_INDEX_NAME}" \
    --data-type float32 \
    --dimension "${EMBEDDING_DIMENSIONS}" \
    --distance-metric cosine \
    --tags "Project=CrewMate,Stage=${STAGE},Purpose=SpecGapKnowledgeBase" \
    --region "${AWS_REGION}" >/dev/null
fi

TRUST_POLICY="$(jq -n \
  --arg account "${ACCOUNT_ID}" \
  --arg region "${AWS_REGION}" \
  '{Version:"2012-10-17",Statement:[{Effect:"Allow",Principal:{Service:"bedrock.amazonaws.com"},Action:"sts:AssumeRole",Condition:{StringEquals:{"aws:SourceAccount":$account},ArnLike:{"AWS:SourceArn":("arn:aws:bedrock:"+$region+":"+$account+":knowledge-base/*")}}}]}')"

if ! aws iam get-role --role-name "${ROLE_NAME}" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "${ROLE_NAME}" \
    --assume-role-policy-document "${TRUST_POLICY}" \
    --description "CrewMate Bedrock Knowledge Base service role" >/dev/null
  ROLE_CREATED=true
else
  aws iam update-assume-role-policy --role-name "${ROLE_NAME}" --policy-document "${TRUST_POLICY}"
fi

ROLE_POLICY="$(jq -n \
  --arg source_bucket "${SOURCE_BUCKET}" \
  --arg vector_index_arn "${VECTOR_INDEX_ARN}" \
  --arg embedding_model_arn "${EMBEDDING_MODEL_ARN}" \
  '{Version:"2012-10-17",Statement:[
    {Sid:"InvokeEmbeddingModel",Effect:"Allow",Action:["bedrock:InvokeModel"],Resource:[$embedding_model_arn]},
    {Sid:"ListKnowledgeSource",Effect:"Allow",Action:["s3:ListBucket"],Resource:[("arn:aws:s3:::"+$source_bucket)],Condition:{StringLike:{"s3:prefix":["knowledge-base","knowledge-base/*"]}}},
    {Sid:"ReadKnowledgeSource",Effect:"Allow",Action:["s3:GetObject"],Resource:[("arn:aws:s3:::"+$source_bucket+"/knowledge-base/*")]},
    {Sid:"UseS3VectorIndex",Effect:"Allow",Action:["s3vectors:PutVectors","s3vectors:GetVectors","s3vectors:DeleteVectors","s3vectors:QueryVectors","s3vectors:GetIndex"],Resource:[$vector_index_arn]}
  ]}')"
aws iam put-role-policy --role-name "${ROLE_NAME}" --policy-name CrewMateKnowledgeBaseAccess --policy-document "${ROLE_POLICY}"
if [[ "${ROLE_CREATED}" == "true" ]]; then
  # IAM is eventually consistent; a new Bedrock service role is not always
  # assumable immediately after CreateRole/PutRolePolicy returns.
  sleep 10
fi

KB_ID="$(aws bedrock-agent list-knowledge-bases --region "${AWS_REGION}" --max-results 100 --query "knowledgeBaseSummaries[?name=='${KB_NAME}'].knowledgeBaseId | [0]" --output text)"
if [[ -z "${KB_ID}" || "${KB_ID}" == "None" ]]; then
  KB_CONFIG="$(jq -n \
    --arg model "${EMBEDDING_MODEL_ARN}" \
    --argjson dimensions "${EMBEDDING_DIMENSIONS}" \
    '{type:"VECTOR",vectorKnowledgeBaseConfiguration:{embeddingModelArn:$model,embeddingModelConfiguration:{bedrockEmbeddingModelConfiguration:{dimensions:$dimensions,embeddingDataType:"FLOAT32"}}}}')"
  STORAGE_CONFIG="$(jq -n \
    --arg index_arn "${VECTOR_INDEX_ARN}" \
    '{type:"S3_VECTORS",s3VectorsConfiguration:{indexArn:$index_arn}}')"
  KB_ID="$(aws bedrock-agent create-knowledge-base \
    --name "${KB_NAME}" \
    --description "CrewMate structured certification and NCS requirement evidence" \
    --role-arn "${ROLE_ARN}" \
    --knowledge-base-configuration "${KB_CONFIG}" \
    --storage-configuration "${STORAGE_CONFIG}" \
    --tags "Project=CrewMate,Stage=${STAGE}" \
    --region "${AWS_REGION}" \
    --query 'knowledgeBase.knowledgeBaseId' --output text)"
fi
wait_for_kb "${KB_ID}"

DATA_SOURCE_ID="$(aws bedrock-agent list-data-sources --knowledge-base-id "${KB_ID}" --region "${AWS_REGION}" --max-results 100 --query "dataSourceSummaries[?name=='${DATA_SOURCE_NAME}'].dataSourceId | [0]" --output text)"
if [[ -z "${DATA_SOURCE_ID}" || "${DATA_SOURCE_ID}" == "None" ]]; then
  DATA_SOURCE_CONFIG="$(jq -n \
    --arg bucket_arn "arn:aws:s3:::${SOURCE_BUCKET}" \
    --arg account "${ACCOUNT_ID}" \
    '{type:"S3",s3Configuration:{bucketArn:$bucket_arn,bucketOwnerAccountId:$account,inclusionPrefixes:["knowledge-base/"]}}')"
  INGESTION_CONFIG='{"chunkingConfiguration":{"chunkingStrategy":"NONE"}}'
  DATA_SOURCE_ID="$(aws bedrock-agent create-data-source \
    --knowledge-base-id "${KB_ID}" \
    --name "${DATA_SOURCE_NAME}" \
    --description "CrewMate reviewed structured and reference evidence" \
    --data-source-configuration "${DATA_SOURCE_CONFIG}" \
    --data-deletion-policy DELETE \
    --vector-ingestion-configuration "${INGESTION_CONFIG}" \
    --region "${AWS_REGION}" \
    --query 'dataSource.dataSourceId' --output text)"
fi
wait_for_data_source "${KB_ID}" "${DATA_SOURCE_ID}"

jq -n \
  --arg accountId "${ACCOUNT_ID}" \
  --arg region "${AWS_REGION}" \
  --arg stage "${STAGE}" \
  --arg sourceBucket "${SOURCE_BUCKET}" \
  --arg vectorBucketName "${VECTOR_BUCKET_NAME}" \
  --arg vectorBucketArn "${VECTOR_BUCKET_ARN}" \
  --arg vectorIndexName "${VECTOR_INDEX_NAME}" \
  --arg vectorIndexArn "${VECTOR_INDEX_ARN}" \
  --arg roleArn "${ROLE_ARN}" \
  --arg knowledgeBaseId "${KB_ID}" \
  --arg dataSourceId "${DATA_SOURCE_ID}" \
  '{accountId:$accountId,region:$region,stage:$stage,sourceBucket:$sourceBucket,vectorBucketName:$vectorBucketName,vectorBucketArn:$vectorBucketArn,vectorIndexName:$vectorIndexName,vectorIndexArn:$vectorIndexArn,roleArn:$roleArn,knowledgeBaseId:$knowledgeBaseId,dataSourceId:$dataSourceId}' \
  > "${STATE_FILE}"

echo "Knowledge Base provisioned: ${KB_ID}"
echo "Data Source: ${DATA_SOURCE_ID}"
echo "State: ${STATE_FILE}"
