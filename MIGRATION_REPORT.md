# PROMPT 1 마이그레이션 보고서 — 백엔드·Agent 계약 v2 + 엔터티별 DB

단일 테이블(v1)을 폐기하고 8개 엔터티 테이블 + 계약 v2로 백엔드·Agent를 개편했다.
**프론트엔드 코드는 한 줄도 수정하지 않았다.** 계약 해석은 `frontend/src/api/`(types/client/mock)의
응답 형태를 기준으로 맞췄다.

---

## 1. DB — 엔터티별 테이블 8종 (`template.yaml`)

| 테이블 | PK | SK | GSI |
|---|---|---|---|
| `CrewMate-Workers-{stage}` | `worker_id` | — | GSI1: `office_id` + `gsi1sk`(`state#worker_id`) |
| `CrewMate-Offices-{stage}` | `office_id` | — | — |
| `CrewMate-Companies-{stage}` | `company_id` | — | — |
| `CrewMate-Requests-{stage}` | `request_id` | — | GSI1: `office_id`+`gsi1sk`(`status#id`) / GSI2: `company_id`+`request_id` |
| `CrewMate-Crews-{stage}` | `crew_id` | — | GSI1: `office_id`+`gsi1sk`(`status#id`) |
| `CrewMate-Assignments-{stage}` | `crew_id` | `worker_id` | GSI1: `worker_id`+`created_at` |
| `CrewMate-GapEvents-{stage}` | `event_id` | — | GSI1: `office_id`+`gsi1sk`(`status#id`) |
| `CrewMate-Notifications-{stage}` | `user_id` | `sk`(`created_at#id`) | — |

- 테이블명은 SAM 파라미터→Lambda 환경 변수(`WORKERS_TABLE` 등)로 주입. IAM은 Lambda별로 필요한 테이블에만 `DynamoDBCrudPolicy`/`DynamoDBReadPolicy` 부여.
- **Assignments 가 CrewMember 의 단일 진실 원천.** Crew 에는 `member_ids` 요약 + `proposed_members`(승인 전 조합) + `recommendations`(AGENT). 승인 후 조원 상세는 Assignments 조인으로 응답 구성.
- 작업 이력(`/worker/history`)·협업 이력은 Assignments GSI1 에서 유도(별도 테이블 없음).
- `worker_id`는 UUID(자가등록 시 = Cognito sub). **주민등록번호 필드 없음.**

---

## 2. 엔드포인트 구현 상태

기존 유지 + 신규 전부 구현(총 35 라우트). Lambda 매핑:

| 엔드포인트 | 메서드 | 담당 Lambda | 상태 |
|---|---|---|---|
| `/auth/signup` | POST | auth | ✅ (public) |
| `/auth/login` | POST | auth | ✅ (public) |
| `/offices` | GET | auth | ✅ (public) |
| `/worker/application` | POST/PUT | worker_api | ✅ |
| `/worker/me` | GET | worker_api | ✅ |
| `/worker/state/ready`·`/inactive` | POST | worker_api | ✅ |
| `/worker/offer/accept` | POST | worker_api | ✅ (트랜잭션 2) |
| `/worker/offer/decline` | POST | worker_api | ✅ (트랜잭션 3) |
| `/worker/assignments` | GET | worker_api | ✅ |
| `/worker/history` | GET | worker_api | ✅ (Assignments 유도) |
| `/company/requests` | POST/GET | company_request | ✅ |
| `/company/requests/{id}` | PUT/GET | company_request | ✅ (+crew/activeGap) |
| `/company/crews/{id}/checkin/{workerId}` | POST | company_request | ✅ (트랜잭션 4) |
| `/company/crews/{id}/checkout/{workerId}` | POST | company_request | ✅ (트랜잭션 5) |
| `/company/crews/{id}/gap-events` | POST | company_request | ✅ (트랜잭션 6) |
| `/office/workers` | GET | office_core | ✅ (성실도 포함) |
| `/office/requests`·`/office/requests/{id}` | GET | office_core | ✅ (토큰 office_id 기준) |
| `/office/requests/{id}/reject` | POST | office_core | ✅ |
| `/office/crews/manual` | POST | office_core | ✅ |
| `/office/crews/{id}/fill-gap` | POST | office_core | ✅ (대체자만 트랜잭션 1 경로) |
| `/office/crews/{id}/cancel-composition` | POST | office_core | ✅ (트랜잭션 7) |
| `/office/cancel-offer` | POST | office_core | ✅ (트랜잭션 7) |
| `/office/gap-events`·`/office/gap-events/{id}` | GET | office_core | ✅ |
| `/office/crews/{id}/approve` | POST | assignment | ✅ (트랜잭션 1) |
| `/office/emergency/{id}/approve` | POST | assignment | ✅ |
| `/office/requests/{id}/agent-compose` | POST | agent_invoke | ✅ (NORMAL) |
| `/office/gap-events/{id}/agent-recompose` | POST | agent_invoke | ✅ (EMERGENCY) |
| `/notifications` | GET | notification | ✅ |
| `/notifications/read` | POST | notification | ✅ |

응답 봉투 `{ success, data }` / `{ success, error:{ code, message } }` 고정. `data`는 프론트 mock과
동일하게 **원시 엔터티/배열**로 반환(v1의 `{workers:[...]}` 래핑 제거).

---

## 3. 트랜잭션 7종 구현 위치 (`shared/txn.py` 엔트리 빌더 + 단일 `TransactWriteItems`)

| # | 전환 | 위치 |
|---|---|---|
| 1 | 승인: 조원 READY→NOTIFIED + current_offer + Assignments 생성 + Crew→NOTIFIED + Request→APPROVED | `functions/assignment/app.py::approve_crew` |
| 2 | 수락: Worker NOTIFIED→RESERVED(+dispatched_count) + Assignment ACCEPTED/RESERVED(+eta) | `functions/worker_api/app.py::accept_offer` |
| 3 | 거절: Worker NOTIFIED→READY + current_offer 제거 + Assignment DECLINED + GapEvent(DECLINED) + Request→COMPOSING(+declined_worker_ids) | `functions/worker_api/app.py::decline_offer` |
| 4 | 출근: Worker RESERVED→RUNNING + current_crew_id + Assignment RUNNING | `functions/company_request/app.py::checkin` |
| 5 | 퇴근: Worker RUNNING→INACTIVE(+completed_count) + offer/crew 정리 + Assignment COMPLETED | `functions/company_request/app.py::checkout` |
| 6 | 결원: 이탈자 INACTIVE + Assignment(유형) + GapEvent(DETECTED) + Request→COMPOSING | `functions/company_request/app.py::create_gap_event` |
| 7 | 제안 취소 / 편성 취소 | `functions/office_core/app.py::cancel_offer` / `::cancel_composition` |

- 원자성: 조원 전원(또는 대체자 전원)을 한 트랜잭션으로 처리. 근로자 전이는 `state ∈ from_states` 조건부 쓰기, 승인은 추가로 **`current_offer` 미보유 조건**(중복 배치 방지 관문). 한 명이라도 실패 시 전체 롤백 → `STATE_CONFLICT`. 부분 변경 없음.
- 전원 수락/전원 출근/전원 퇴근 시 Crew·Request 롤업(DISPATCHED/RUNNING/COMPLETED)은 파생 갱신으로 처리.

---

## 4. 성실도 규칙 (법적 리스크 회피 — 엄수)

- 저장은 원시값 `completed_count` / `dispatched_count` 만. 파생 필드·비율 저장 없음.
- 분모(+1)는 **수락(RESERVED 확정)** 시(트랜잭션 2), 분자(+1)는 **정상 퇴근** 시(트랜잭션 5). 노쇼·이탈·수락 후 취소·거절은 분자 미증가.
- 노출 범위: **OFFICE 응답에만** 포함(`worker_office_view`). WORKER 본인(`worker_self_view`)·COMPANY(`worker_public_view`) 응답에서 제외.
- `no_show_count` 등 부정 라벨 필드는 **저장·반환하지 않음**. API 응답/오류 메시지에 "노쇼/탈주/블랙리스트" 문자열 없음(enum 코드 `NO_SHOW` 등만 내부 사용).

---

## 5. Agent (Crew Composition Agent) 개편

- 입력 후보에 `preferred_trades[]`·`excluded_trades[]`·`desired_daily_wage` 포함. 추천 멤버에 **`assigned_trade`** 포함(`trade` 대체).
- 코드 검증(`agent_invoke/app.py::_valid_rec`): 후보 실존·READY, `assigned_trade ∉ excluded_trades`, 필수 직종·인원 정확 충족, 예산(NORMAL=budget / EMERGENCY=budget−고정 인원 합) 이내, 중복 없음.
- EMERGENCY 후보에서 해당 요청 `declined_worker_ids` 및 고정 인원 제외. fixed_members 불변.
- 추천 사유에 개인 부정 평가·확률 수치·최적 보장 표현 금지(system_prompt + 결정론 사유 문자열).
- Tool 읽기 전용 4종 유지, 새 테이블 기준 재구현. LLM(Strands+Bedrock) 추천 시도 → 검증 실패 시 1회 재시도 → 실패/미가용 시 **결정론적 폴백**(seed=42 그리디)으로 동일 규칙 추천 생성(데모 안정성). 후보 부족 시 `AGENT_RETRY_FAILED`.

---

## 6. 시드 (`scripts/seed/`, seed=42, 리셋 지원)

- `seed_workers.py`: 사무소 2곳(OFFICE001 부산/OFFICE002 김해), 건설사 2곳, 근로자 60명(희망/비희망 직종, 성실도 다양화), 요청 7건. `--reset`으로 전체 초기화.
- `seed_history.py`: 완료 작업조 + Assignments(작업/협업 이력 원천).
- `seed_demo_scenario.py`: A·B·C RUNNING(crew DEMO-CREW-001) + D·E·F·G READY. E는 A·B와 과거 협업 이력, G는 성실도 낮음(Agent 종합 판단 시연용).
- `seed_cognito.py`: 데모 계정 `worker1/2/3`·`office1`·`company1`(공통 pw `demo1234`) 생성 + 대응 Worker/Office/Company 레코드 연결(owner_user_id = Cognito sub).

---

## 7. 검증 결과

- **단위/통합 테스트**: `pytest` → **7 passed** (`tests/test_v2_flow.py`, moto 8테이블).
  1. 지원서 등록 → READY, 성실도 미노출 확인
  2. 수동 편성 → 승인(전원 NOTIFIED) → 수락(DISPATCHED, dispatched_count+1) → 출근(RUNNING) → 퇴근(COMPLETED, completed_count+1) → 이력 조회
  3. 거절 → GapEvent(DECLINED) + declined_worker_ids 반영 + Request COMPOSING + Worker READY
  4. 동시성: 같은 READY 근로자 이중 승인 → 한쪽만 성공, 다른 쪽 `STATE_CONFLICT`, 부분 변경 없음
  5. 성실도 노출: OFFICE 응답 포함 / COMPANY 응답 미포함
  6. Agent 편성: 추천안 생성(각 멤버 `assigned_trade`, total_cost 일관)
- **노출 검증(grep)**: `no_show_count|노쇼|탈주|블랙리스트` — 백엔드 매치 0건.
- **템플릿**: `sam validate --lint` → valid. 라우트 35개 확인(`scripts/validate_template.py`).
- **임포트 스모크**: 8개 Lambda 핸들러 + agent 패키지 임포트 OK.

미실행(팀/배포 단계): `sam build`(레이어 의존성 다운로드 필요), `sam deploy`, 배포 후 `seed_cognito.py`.

---

## 8. 미해결 이슈 / 계약 해석 결정 (PROMPT_2에서 확인 필요)

1. **성실도 노출 vs 프론트 타입**: 프론트 `Worker` 타입은 `completed_count`/`no_show_count`를 필수로 선언하나, PROMPT §3/README §4의 "인력사무소 한정" 규칙을 우선해 WORKER 본인·COMPANY 응답에서 성실도를 제외하고 `no_show_count`는 저장·반환하지 않음. 현재 렌더링되는 화면(WorkersPage 등)에는 영향 없음을 확인. PROMPT_2에서 프론트 표기 재확인 권장.
2. **상태 전이값 = PROMPT §2 기준(간소화된 mock과 상이)**: 응답 *형태*는 mock을 따르되, 아래 전이 *값*은 명세(§2)를 따랐다.
   - 거절 시 근로자 → **READY** (mock은 INACTIVE)
   - 제안 취소 시 근로자 → **READY** (mock은 INACTIVE)
   - 편성 취소 시 요청 → **REQUESTED** (mock은 CANCELLED)
   PROMPT_2 E2E에서 프론트 표시와 어긋나면 백엔드를 프론트 기대에 맞춰 조정.
3. **gap_event Lambda + EventBridge 제거**: agent-recompose가 동기 HTTP로 전환되어 프론트가 비동기 경로를 사용하지 않으므로 EventBridge 컨슈머를 폐기(명세에 없는 기능 미추가 원칙). 자동 결원 감지가 필요하면 별도 합의.
4. **알림 대상(office/company)**: 근로자 알림은 `worker.user_id`로 정확히 전달. 사무소/건설사 알림은 가입 시 저장한 `owner_user_id`(Cognito sub)로 전달 — `seed_cognito.py`가 데모 계정에 이를 연결. 시드된 합성 사무소/건설사는 owner가 없어 알림이 조회되지 않을 수 있음(데모 무관, best-effort).
5. **Bedrock 미검증**: LLM 경로는 배포 환경에서만 동작. 로컬/테스트·Bedrock 실패 시 결정론적 폴백이 항상 유효 추천을 생성하도록 설계했으나, 실제 Bedrock 추천 품질은 배포 후 확인 필요.

---

## 9. 산출물

- `template.yaml` (8테이블 + GSI + IAM + Cognito username 풀 + 라우트)
- `backend/shared/` (db·state·schemas·crew·responses·auth·routing·**txn** 신규)
- `backend/functions/` (auth 신규 + worker_api·company_request·office_core·assignment·notification·agent_invoke 재작성)
- `backend/agent/` (schemas·tools·system_prompt v2)
- `scripts/seed/` (8테이블 재작성)
- `tests/` (moto 8테이블 통합 테스트)
