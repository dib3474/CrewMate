# PROMPT 2 — 모노레포 통합 · real 전환 · E2E 디버깅 (AI 에이전트 입력용)

> `PROMPT_1_BACKEND_REBUILD.md` 완료(curl 검증 전부 통과) 후 새 세션에서 실행한다.
> `[여기에 ...]` 표시는 실행 전에 팀이 채운다.

---

너는 CrewMate 프로젝트의 통합 담당 엔지니어다. 백엔드·Agent는 계약 v2와 엔터티별 DB로 개편이 끝났고, 프론트엔드는 mock 모드로 배포되어 있다(https://d1872k8ivu18th.cloudfront.net). 너의 임무는 세 파트를 하나의 모노레포로 정리하고, 프론트엔드를 real API 모드로 전환해 E2E 데모 시나리오를 전부 통과시키는 것이다.

---

## 절대 규칙

1. 디버깅 우선순위·수정 방향: **프론트엔드(1) > Agent(2) > 백엔드(3)**. 프론트와 백엔드가 어긋나면 백엔드를 프론트 기대에 맞게 고친다. 프론트 수정은 (a) mock↔real 전환 설정, (b) 명백한 프론트 버그, (c) 아래 Phase 4 목록에 한정한다.
2. 응답 봉투·상태 enum·성실도 노출 규칙(OFFICE 한정)·Agent 읽기 전용 원칙은 PROMPT 1과 동일하게 유지. 위반을 발견하면 백엔드를 고친다.
3. 크리덴셜 하드코딩 금지. 발견 즉시 환경 변수 이전 + 보고. git 이력에 키가 있으면 키 재발급 필요를 보고서에 명시.
4. 전면 재작성 금지, 최소 diff. Phase마다 커밋.

## Phase 1 — 조사 (수정 금지)

세 파트 전체를 읽고 보고: (a) 목표 구조 대비 파일 배치, (b) 프론트 mock 응답 vs 백엔드 실제 응답의 필드 단위 차이(엔드포인트별 표), (c) 중복 모듈, (d) 하드코딩된 URL·크리덴셜, (e) CORS 설정 상태. 사용자 확인 후 진행.

## Phase 2 — 물리 통합

1. 목표 구조로 이동·병합, 중복 모듈은 backend/shared/로 통일.
2. 환경 변수 정리: `VITE_API_BASE_URL`, `VITE_API_MODE=mock|real`, Cognito 설정. `.env.example` 작성.
3. CORS: API Gateway 허용 오리진에 `https://d1872k8ivu18th.cloudfront.net`과 로컬 개발 오리진 등록. 프리플라이트(OPTIONS)와 오류 응답에도 CORS 헤더가 붙는지 확인 — 오류 응답에 헤더가 빠지는 것이 통합 단계 최다 빈도 버그다.
4. 빌드 전부 통과: `sam build && sam deploy`, `npm run build`, 시드 실행.

## Phase 3 — real 전환 + E2E 디버깅

`VITE_API_MODE=real`로 전환하고 시드를 넣은 뒤, 프론트 화면 기준으로 아래를 순서대로 통과시킨다. 실패 시 Phase 1의 차이 표를 참고해 최소 수정.

1. **가입·로그인**: 3역할 signup → login → 역할별 홈 진입. OFFICE 가입 시 `GET /offices` 목록에 신규 사무소 표시.
2. **일반 편성 풀 사이클**: WORKER 지원서 → 대기 → COMPANY 요청 → OFFICE AI 편성 → 추천 카드(assigned_trade·offered_wage 표시) → 임금 조절 → 승인 → WORKER 앱에 제안 도착(폴링) → 수락 → 전원 수락 시 DISPATCHED → COMPANY 출근 처리 → RUNNING → 퇴근 처리 → 이력·성실도 반영.
3. **거절 → 추가 편성**: 조원 1명 거절 → GapEvent(DECLINED) → 요청 COMPOSING 표시 → fill-gap(수동)과 agent-recompose(AI) 각각 1회씩 → 대체자 수락 → FILLED.
4. **노쇼 → 긴급 배차**: RUNNING 작업조에서 노쇼 시뮬레이션 → EMERGENCY 추천(잔여 예산 검증) → 승인 → 대체자 수락 → 작업조 갱신 → COMPANY 화면 반영, 신규 투입자 강조 표시.
5. **동시성·폴백**: 같은 READY 근로자 이중 승인 → STATE_CONFLICT 안내 UI. Agent 강제 실패 → 수동 편성 유도 UI.
6. **노출 검증**: COMPANY 화면·응답에 성실도 카운트 및 부정 라벨 부재. OFFICE 후보 목록에 성실도 `10/11` 형식 표시.

## Phase 4 — 프론트엔드 기능 추가·수정

각 항목 완료 시 관련 시나리오 재실행으로 회귀 확인.

```text
[여기에 프론트엔드 수정·추가 항목을 팀이 채운다]
```

## 완료 기준

- Phase 3의 1~6이 배포된 CloudFront URL에서 연속 통과.
- 소스에 크리덴셜 없음, `.env.example` 존재.
- 최종 보고서: 수정 파일 목록(파트별), 프론트를 수정한 항목과 사유, 남은 이슈, 데모 리허설 체크리스트.
