# PROMPT 1 — 백엔드·Agent 개편: 계약 v2 + 엔터티별 DB (AI 에이전트 입력용)

> 이 프롬프트를 먼저 실행한다. 완료 후 새 세션에서 `PROMPT_2_INTEGRATION_E2E.md`를 실행한다.
> `[여기에 ...]` 표시는 실행 전에 팀이 채운다.

---

너는 CrewMate 프로젝트의 백엔드 리드 엔지니어다. 프론트엔드는 이미 계약 v2 기준으로 구현·배포 완료되었고(mock 모드, https://d1872k8ivu18th.cloudfront.net), **프론트엔드가 기대하는 계약이 유일한 진실**이다. 너의 임무는 백엔드와 Agent를 계약 v2에 맞게 개편하고, DB를 엔터티별 테이블 구조로 구현하는 것이다. 이 단계에서 프론트엔드 코드는 한 줄도 수정하지 않는다.

---

## 절대 규칙

1. 프론트엔드 무수정. 계약 해석이 갈리면 프론트엔드 mock 레이어의 응답 형태(`frontend/` 내 mock 구현)를 기준으로 백엔드를 맞춘다.
2. 응답 봉투는 `{ success: true, data }` / `{ success: false, error: { code, message } }` 고정.
3. Agent는 조회·추천만 한다. 쓰기 Tool 금지, 자동 승인 금지, 자동 수락 금지.
4. ML 모델·SageMaker·GPS·WebSocket 추가 금지. 서버리스(SAM) 유지.
5. 크리덴셜 하드코딩 금지. 발견 시 환경 변수로 이전하고 보고.
6. 다중 테이블 상태 전환은 반드시 하나의 `TransactWriteItems`로 원자 처리. 테이블별 순차 쓰기 금지.
7. 아래 명세에 없는 기능·테이블·엔드포인트를 임의로 추가하지 않는다. 필요하다고 판단되면 구현하지 말고 사유를 보고한다.

## 1. DB 목표 스키마 (엔터티별 테이블, DynamoDB)

기존 단일 테이블을 폐기하고 아래 8개 테이블로 구현한다. 테이블명 접두사 `CrewMate-`, 이름은 SAM 파라미터로 Lambda 환경 변수에 주입. IAM은 테이블별 최소 권한.

| 테이블 | PK | SK | GSI |
|---|---|---|---|
| Workers | `worker_id` | — | GSI1: `office_id` + `state#worker_id` |
| Offices | `office_id` | — | — |
| Companies | `company_id` | — | — |
| Requests | `request_id` | — | GSI1: `office_id`+`status#request_id` / GSI2: `company_id`+`request_id` |
| Crews | `crew_id` | — | GSI1: `office_id`+`status#crew_id` |
| Assignments | `crew_id` | `worker_id` | GSI1: `worker_id`+`created_at` |
| GapEvents | `event_id` | — | GSI1: `office_id`+`status#event_id` |
| Notifications | `user_id` | `created_at#notification_id` | — |

핵심 필드:

- **Workers**: `worker_id(UUID), user_id, name, phone, region, office_id, state, preferred_trades[], excluded_trades[], skill_level(1~5), career_years, age, desired_daily_wage, certifications[], completed_count, dispatched_count, current_crew_id, current_offer{crew_id, request_id, site_name, work_date, start_time, assigned_trade, offered_wage, notified_at}, state_changed_at, created_at, updated_at`. 주민등록번호 필드 금지.
- **Offices**: `office_id, name, region, location_text, owner_name, phone, created_at` (OFFICE 회원가입 시 자동 생성)
- **Requests**: 기존 필드 + `rejection_reason`, `declined_worker_ids[]`
- **Assignments** (CrewMember의 단일 진실 원천): `crew_id, worker_id, assigned_trade, offered_wage, acceptance(PENDING|ACCEPTED|DECLINED), is_replacement(bool), eta, notified_at, status(RESERVED|RUNNING|COMPLETED|CANCELLED|NO_SHOW|LEFT_SITE|DECLINED), created_at, updated_at`
- **Crews**: `crew_id, request_id, office_id, status, member_ids[](요약), source(AGENT|MANUAL), total_cost, reason, considerations[], created_at`. 멤버 상세는 Assignments 조인으로 응답 구성.
- **GapEvents**: `event_id, crew_id, request_id, office_id, type(NO_SHOW|LEFT_SITE|UNAVAILABLE|DECLINED), leaver_worker_id, status, created_at`
- **Notifications**: 기존 + `read(bool)`
- 작업 이력(`/worker/history`)과 협업 이력은 Assignments GSI1에서 유도한다. 별도 테이블 금지.

## 2. 상태 머신 v2 와 트랜잭션

```text
Worker:  INACTIVE → READY → NOTIFIED → RESERVED → RUNNING → INACTIVE
         NOTIFIED → READY (거절/제안취소), RESERVED → READY (수락 후 취소/편성 취소)
Request: REQUESTED → COMPOSING → PROPOSED → APPROVED → DISPATCHED → RUNNING → COMPLETED (+CANCELLED, REJECTED)
Crew:    DRAFT → PROPOSED → APPROVED → NOTIFIED → DISPATCHED → RUNNING → COMPLETED (+CANCELLED)
GapEvent: DETECTED → RECOMPOSING → PROPOSED → APPROVED → FILLED (+FAILED)
```

각 전환의 원자 처리 (하나의 TransactWriteItems):

1. **승인**(`/office/crews/{id}/approve`): 조원 전원 Workers `READY→NOTIFIED`(조건 `state=READY`) + `current_offer` 기록 + Assignments 생성(acceptance=PENDING) + Crew `→NOTIFIED` + Request `→APPROVED`. 한 명이라도 실패 시 전체 롤백, `STATE_CONFLICT`. 근로자가 이미 `current_offer`를 가진 경우도 실패 조건.
2. **수락**(`/worker/offer/accept`, body: eta?): Worker `NOTIFIED→RESERVED` + Assignment `acceptance=ACCEPTED, status=RESERVED, eta` (조건 PENDING) + `dispatched_count += 1` + `current_offer` 유지. 이후 별도 확인 로직으로 전원 ACCEPTED면 Crew·Request `→DISPATCHED`.
3. **거절**(`/worker/offer/decline`): Worker `NOTIFIED→READY` + `current_offer` 제거 + Assignment `DECLINED` + GapEvent(type=DECLINED) 생성 + Request `declined_worker_ids`에 추가, Request `→COMPOSING`.
4. **출근**(`/company/crews/{id}/checkin/{workerId}`): Worker `RESERVED→RUNNING` + Assignment `→RUNNING` + `current_crew_id` 기록. 전원 출근 시 Crew·Request `→RUNNING`.
5. **퇴근**(`/company/crews/{id}/checkout/{workerId}`): Worker `RUNNING→INACTIVE` + `completed_count += 1` + `current_offer/current_crew_id` 정리 + Assignment `→COMPLETED`. 전원 퇴근 시 Crew·Request `→COMPLETED`.
6. **결원**(`/company/crews/{id}/gap-events`, type: NO_SHOW|LEFT_SITE|UNAVAILABLE): 이탈자 Worker `→INACTIVE`(성실도: completed 증가 없음) + Assignment를 해당 유형으로 + GapEvent(DETECTED) + Request `→COMPOSING`.
7. **제안 취소**(`/office/cancel-offer`): 무응답 근로자 `NOTIFIED→READY` + Assignment `CANCELLED`. **편성 취소**(`/office/crews/{id}/cancel-composition`): 전 조원 원상 복구(NOTIFIED/RESERVED→READY) + Crew `CANCELLED` + Request `→REQUESTED`.

## 3. 성실도 규칙 (법적 리스크 회피 설계 — 엄수)

- 저장은 `completed_count`/`dispatched_count` 원시값만. 파생 필드·비율 저장 금지.
- 분모 +1은 수락(RESERVED 확정) 시, 분자 +1은 정상 퇴근 시. 노쇼·이탈·수락 후 취소는 분자 미증가. 제안 거절은 미집계.
- 성실도(두 카운트)는 OFFICE 응답에만 포함한다. COMPANY 응답, WORKER 간 상호 조회, Agent 추천 사유 텍스트에 포함 금지.
- API 응답·오류 메시지에 "노쇼", "탈주", "블랙리스트" 등 부정 라벨 문자열 사용 금지 (enum 코드 값은 예외).

## 4. 구현할 엔드포인트

기존 계약 유지분: `/worker/me`, `/worker/application`(POST/PUT), `/worker/state/ready|inactive`, `/worker/assignments`, `/company/requests`(CRUD), `/company/crews/{id}/gap-events`, `/office/workers`, `/office/crews/manual`, `/office/crews/{id}/approve`, `/office/requests/{id}/agent-compose`, `/office/gap-events/{id}/agent-recompose`, `/office/emergency/{id}/approve`, `GET /notifications`

신규 구현:

| 엔드포인트 | 처리 |
|---|---|
| `POST /auth/signup` | Cognito User Pool 가입 + 역할 그룹 + custom claim(role, office_id/company_id, region). OFFICE 가입 시 Offices 레코드 자동 생성, COMPANY 가입 시 Companies 레코드 생성 |
| `POST /auth/login` | Cognito 인증 래핑, 토큰 + 역할 반환 (프론트가 Cognito SDK를 직접 쓰지 않는 A안) |
| `GET /offices` | 사무소 목록 (가입·요청 화면의 선택 리스트) |
| `POST /worker/offer/accept` | 트랜잭션 2 |
| `POST /worker/offer/decline` | 트랜잭션 3 |
| `GET /worker/history` | Assignments GSI1에서 완료 이력 |
| `POST /company/crews/{id}/checkin/{workerId}` | 트랜잭션 4 |
| `POST /company/crews/{id}/checkout/{workerId}` | 트랜잭션 5 |
| `GET /office/requests`, `GET /office/requests/{id}` | GSI1 조회. **토큰의 office_id 기준** (하드코딩 금지) |
| `GET /office/gap-events`, `GET /office/gap-events/{id}` | GSI1 조회 |
| `POST /office/requests/{id}/reject` (body: reason) | Request `→REJECTED` + rejection_reason + COMPANY 알림 |
| `POST /office/crews/{id}/fill-gap` | 수동 추가 편성: fixed_members 유지, 결원만 신규 지정 → 승인 시 대체자만 트랜잭션 1 경로 |
| `POST /office/cancel-offer` (body: worker_id) | 트랜잭션 7 |
| `POST /office/crews/{id}/cancel-composition` | 트랜잭션 7 |
| `POST /notifications/read` (body: ids) | read=true 일괄 처리 |

공통 검증: 편성·승인 시 `assigned_trade ∉ worker.excluded_trades`, `sum(offered_wage) ≤ request.budget`, 필수 직종·인원 충족. `offered_wage` 미지정 시 `desired_daily_wage` 사용.

## 5. Agent 수정 (Crew Composition Agent)

- 입력 후보에 `preferred_trades[]`, `excluded_trades[]`, `desired_daily_wage` 포함. 추천 결과의 각 멤버에 **`assigned_trade`** 포함 (기존 `trade` 필드명 대체 — 프론트 계약).
- 검증(Lambda 코드): 후보 실존, 신규 후보 전원 READY, `assigned_trade ∉ excluded_trades`, 예산(NORMAL: budget, EMERGENCY: budget − fixed_members offered_wage 합), 필수 직종 충족, fixed_members 불변, `declined_worker_ids` 제외.
- EMERGENCY 후보 조회 시 해당 Request의 `declined_worker_ids`를 후보에서 제외한다.
- 추천 사유 텍스트에 개인 부정 평가·확률 수치·최적 보장 표현 금지. 검증 실패 시 1회 재시도 → `AGENT_RETRY_FAILED`.
- Tool은 읽기 전용 4종 유지(get_request_detail / get_ready_workers / get_worker_history / get_current_crew) — 새 테이블 기준으로 재구현.

## 6. 시드 스크립트

새 테이블 기준으로 재작성 (`seed=42`, 리셋 모드 지원):

- 사무소 2곳, 건설사 2곳, 근로자 50~100명(희망/비희망 직종 배열, 성실도 카운트 다양화), 요청 5~10건
- 데모 세트: 작업조 A·B·C(RUNNING) + D·E·F(READY, E는 A·B와 협업 이력) + 성실도가 낮은 근로자 1~2명(READY, Agent가 종합 판단하는 모습 시연용)
- 시드 계정: 기존 데모 계정 3종 유지 + signup 테스트용 여유

## 7. 검증 (프론트 없이, curl/스크립트로)

아래가 전부 통과해야 완료다. 각 단계 응답 JSON이 프론트 mock 레이어의 응답 형태와 필드 단위로 일치하는지 비교한다.

1. signup(3역할) → login → 역할별 토큰 claim 확인, OFFICE 가입 시 Offices 레코드 생성 확인
2. 지원서 → READY → 요청 생성 → agent-compose → 추천(각 멤버 assigned_trade 포함) → 임금 수정 승인 → 전원 NOTIFIED
3. 수락 2명 + 거절 1명 → 거절자 READY 복귀, GapEvent(DECLINED), Request COMPOSING, declined_worker_ids 반영
4. fill-gap 또는 agent-recompose → 대체자 승인·수락 → FILLED → 전원 checkin → RUNNING → checkout → COMPLETED, 성실도 카운트 증가 확인
5. 동시성: 같은 READY 근로자를 두 작업조로 동시 승인 → 한쪽만 성공, 다른 쪽 STATE_CONFLICT, 부분 변경 없음
6. COMPANY 응답에 성실도 카운트·부정 라벨이 없는지 grep 검증

## 8. 산출물

- 변경된 template.yaml(8테이블+GSI+IAM), shared/db 레이어, Lambda 전체, agent, 시드
- 마이그레이션 보고서: 엔드포인트별 구현 상태 표, 트랜잭션 7종 구현 위치, 검증 결과, 미해결 이슈
