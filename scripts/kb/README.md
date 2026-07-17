# Bedrock Knowledge Base 배포

이 디렉터리는 서울 리전(`ap-northeast-2`)에서 S3 Vectors를 벡터 저장소로 사용하는
Amazon Bedrock Knowledge Base를 생성하고, 구조화 규칙과 검색 문서를 동기화한다.
보고서 출력 버킷은 데이터 소스에 연결하지 않는다.

## 전제 조건

- AWS CLI v2, SAM CLI, `jq`, `uv`
- 로컬 Python 3.13 또는 Docker
- Bedrock, S3, S3 Vectors, IAM, CloudFormation을 생성할 수 있는 AWS 자격 증명
- Titan Text Embeddings v2 및 보고서 모델 사용 권한

기본 보고서 모델은 현재 유효한 시스템 inference profile
`global.anthropic.claude-sonnet-4-6`이며 `REPORT_MODEL_ID`로 바꿀 수 있다.
전체 배포 스크립트는 CloudFormation 변경 전에 해당 profile의 존재를 검증한다.

## 전체 자동 배포

```bash
AWS_REGION=ap-northeast-2 STAGE=dev STACK_NAME=crewmate ./scripts/kb/deploy-all.sh
```

다른 추론 프로필을 사용할 때는 `REPORT_MODEL_ID`와 그 프로필이 호출하는
`REPORT_FOUNDATION_MODEL_ID`를 함께 지정한다. 두 값은 Lambda의 모델 호출 IAM
권한을 해당 추론 프로필과 기반 모델로 제한하는 데 사용된다.

명령은 다음 순서로 멱등 실행된다.

1. SAM 스택을 빌드·배포해 Knowledge Source/Report 버킷, DynamoDB, Lambda를 만든다.
2. S3 Vector Bucket/Index와 최소 권한 Bedrock 서비스 역할을 만든다.
3. Bedrock Knowledge Base와 S3 Data Source를 만든다.
4. `Archive/` 원본을 규칙 CSV와 record-based KB CSV로 변환해 S3에 동기화한다.
5. ingestion 완료를 기다리고 필터가 적용된 실제 `retrieve` 스모크 테스트를 수행한다.
6. 검증된 KB ID를 Lambda 환경변수와 IAM 리소스에 연결한다.

생성된 식별자는 Git에서 제외된 `.aws-kb/<stage>.json`에 저장된다.

## 부분 실행

```bash
./scripts/kb/provision.sh   # KB/S3 Vectors/Data Source 생성 또는 재사용
./scripts/kb/sync.sh        # 데이터 변환, S3 sync, ingestion
./scripts/kb/smoke-test.sh  # 실제 Bedrock Retrieve + metadata filter 검증
./scripts/kb/status.sh      # KB와 최근 ingestion 상태
```

환경변수 `AWS_REGION`, `STAGE`, `STACK_NAME`, `KNOWLEDGE_SOURCE_BUCKET`,
`KNOWLEDGE_BASE_ID`, `KNOWLEDGE_BASE_DATA_SOURCE_ID`로 대상을 재정의할 수 있다.
S3 Vectors와 Bedrock 모델 호출은 사용량에 따라 AWS 비용이 발생한다.
