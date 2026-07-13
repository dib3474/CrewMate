// === 공유 계약 기반 타입 정의 ===

// 역할
export type UserRole = 'WORKER' | 'OFFICE' | 'COMPANY';

// 근로자 상태
// INACTIVE → READY → NOTIFIED → RESERVED → RUNNING → INACTIVE
export type WorkerState = 'INACTIVE' | 'READY' | 'NOTIFIED' | 'RESERVED' | 'RUNNING';

// 수락 상태
export type AcceptanceStatus = 'PENDING' | 'ACCEPTED' | 'DECLINED';

// 요청 상태
export type WorkRequestStatus =
  | 'REQUESTED'
  | 'COMPOSING'
  | 'PROPOSED'
  | 'APPROVED'
  | 'DISPATCHED'
  | 'RUNNING'
  | 'COMPLETED'
  | 'REJECTED'
  | 'CANCELLED';

// 작업조 상태
export type CrewStatus =
  | 'DRAFT'
  | 'PROPOSED'
  | 'APPROVED'
  | 'NOTIFIED'
  | 'DISPATCHED'
  | 'RUNNING'
  | 'COMPLETED'
  | 'CANCELLED';

// 결원 이벤트 상태
export type GapEventStatus =
  | 'DETECTED'
  | 'RECOMPOSING'
  | 'PROPOSED'
  | 'APPROVED'
  | 'FILLED'
  | 'FAILED';

// 결원 유형
export type GapEventType = 'NO_SHOW' | 'LEFT_SITE' | 'UNAVAILABLE' | 'DECLINED';

// 직종
export type Trade =
  | 'FORMWORK'
  | 'REBAR'
  | 'MASONRY'
  | 'MATERIAL_CARRY'
  | 'GENERAL';

// 우선순위 레벨
export type PriorityLevel = 'HIGH' | 'MEDIUM' | 'LOW';

// === API 응답 형식 ===

export interface ApiSuccessResponse<T> {
  success: true;
  data: T;
}

export interface ApiErrorResponse {
  success: false;
  error: {
    code: string;
    message: string;
  };
}

export type ApiResponse<T> = ApiSuccessResponse<T> | ApiErrorResponse;

// === 엔터티 ===

export interface Office {
  office_id: string;
  name: string;
  region: string;
  worker_count: number;
  active: boolean; // 현재 요청 접수 가능 여부
}

export interface Worker {
  worker_id: string;
  user_id: string;
  name: string;
  phone: string;
  office_id: string;
  state: WorkerState;
  // 직종: 단일이 아닌 희망/비희망 복수 선택
  preferred_trades: Trade[];
  excluded_trades: Trade[];
  skill_level: number;
  career_years: number;
  age: number;
  region: string;
  desired_daily_wage: number;
  certifications: string[];
  completed_count: number;
  no_show_count: number;
  current_crew_id: string | null;
  // 현재 배정 제안 정보 (NOTIFIED 상태일 때)
  current_offer?: {
    crew_id: string;
    assigned_trade: Trade;
    offered_wage: number;
    site_name: string;
    work_date: string;
    start_time: string;
    location_text: string;
    is_emergency?: boolean; // 긴급 배차 제안 여부 (수락 시 예상 도착시간 선택)
  } | null;
  state_changed_at: string;
  created_at: string;
  updated_at: string;
  // 작업 이력
  work_history: WorkHistoryEntry[];
}

export interface WorkHistoryEntry {
  crew_id: string;
  request_id: string;
  site_name: string;
  work_date: string;
  assigned_trade: Trade;
  offered_wage: number;
  completed_at: string;
}

export interface RequiredWorker {
  trade: Trade;
  count: number;
}

export interface Priority {
  cost: PriorityLevel;
  skill: PriorityLevel;
  teamwork: PriorityLevel;
}

export interface WorkRequest {
  request_id: string;
  company_id: string;
  office_id: string;
  site_name: string;
  work_date: string;
  start_time: string;
  location_text: string;
  required_workers: RequiredWorker[];
  budget: number;
  priority: Priority;
  notes: string;
  status: WorkRequestStatus;
  rejection_reason?: string;
  declined_worker_ids?: string[];
  created_at: string;
  updated_at: string;
}

export interface CrewMember {
  worker_id: string;
  name: string;
  assigned_trade: Trade;
  skill_level: number;
  offered_wage: number;
  acceptance: AcceptanceStatus;
  notified_at?: string;
  is_replacement?: boolean; // 긴급 재편성/빈자리 채우기로 신규 투입된 인원
  eta?: string; // 긴급 배차 대체 인력의 예상 도착시간
}

export interface Recommendation {
  rank: number;
  member_ids: string[];
  members: CrewMember[];
  total_cost: number;
  reason: string;
  considerations: string[];
}

export interface Crew {
  crew_id: string;
  request_id: string;
  office_id: string;
  status: CrewStatus;
  source: 'MANUAL' | 'AGENT';
  member_ids: string[];
  members: CrewMember[];
  recommendations?: Recommendation[];
  created_at: string;
  updated_at: string;
}

export interface GapEvent {
  event_id: string;
  crew_id: string;
  request_id: string;
  office_id: string;
  type: GapEventType;
  affected_worker_id: string;
  affected_worker_name?: string;
  status: GapEventStatus;
  recommendations?: Recommendation[];
  created_at: string;
  updated_at: string;
}

export interface Notification {
  id: string;
  user_id: string;
  type: string;
  title: string;
  message: string;
  read: boolean;
  created_at: string;
}

// === 인증 ===

export interface AuthUser {
  userId: string;
  role: UserRole;
  name: string;
  region?: string;
  token: string;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface SignupRequest {
  username: string;
  password: string;
  role: UserRole;
  name: string;
  region?: string; // 인력사무소 가입 시 활동 지역
}

export interface LoginResponse {
  user: AuthUser;
}

// === Worker API 요청 ===

export interface WorkerApplicationRequest {
  name: string;
  phone: string;
  office_id: string;
  preferred_trades: Trade[];
  excluded_trades: Trade[];
  skill_level: number;
  career_years: number;
  age: number;
  region: string;
  desired_daily_wage: number;
  certifications: string[];
  introduction?: string;
}

// === Company API 요청 ===

export interface CreateWorkRequestPayload {
  office_id: string;
  site_name: string;
  work_date: string;
  start_time: string;
  location_text: string;
  required_workers: RequiredWorker[];
  budget: number;
  priority: Priority;
  notes: string;
}

export interface CreateGapEventPayload {
  type: GapEventType;
  affected_worker_id: string;
}
