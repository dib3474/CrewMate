import type {
  AuthUser,
  Worker,
  WorkRequest,
  Crew,
  GapEvent,
  Notification,
  Trade,
} from '../types';

// 시드 데모 계정 3종
export const SEED_ACCOUNTS: Record<string, { password: string; user: AuthUser }> = {
  worker1: {
    password: 'demo1234',
    user: {
      userId: 'USER_WORKER_001',
      role: 'WORKER',
      name: '김건우',
      token: 'mock-token-worker1',
    },
  },
  office1: {
    password: 'demo1234',
    user: {
      userId: 'USER_OFFICE_001',
      role: 'OFFICE',
      name: '부산인력사무소',
      token: 'mock-token-office1',
    },
  },
  company1: {
    password: 'demo1234',
    user: {
      userId: 'USER_COMPANY_001',
      role: 'COMPANY',
      name: '해운대건설',
      token: 'mock-token-company1',
    },
  },
};

// 메모리 상태 — 시나리오 진행용
export interface MockState {
  workers: Worker[];
  requests: WorkRequest[];
  crews: Crew[];
  gapEvents: GapEvent[];
  notifications: Notification[];
}

// 시드 근로자 데이터
const SEED_WORKERS: Worker[] = [
  {
    worker_id: 'W001',
    user_id: 'USER_WORKER_001',
    name: '김건우',
    phone: '010-1234-5678',
    office_id: 'OFFICE001',
    state: 'INACTIVE',
    trade: 'FORMWORK',
    skill_level: 4,
    career_years: 8,
    age: 35,
    region: '부산 해운대구',
    desired_daily_wage: 180000,
    certifications: ['건설기능사', '안전교육이수'],
    completed_count: 42,
    no_show_count: 0,
    current_crew_id: null,
    state_changed_at: '2026-07-10T08:00:00Z',
    created_at: '2026-01-15T09:00:00Z',
    updated_at: '2026-07-10T08:00:00Z',
  },
  {
    worker_id: 'W002',
    user_id: 'USER_WORKER_002',
    name: '박철수',
    phone: '010-2345-6789',
    office_id: 'OFFICE001',
    state: 'READY',
    trade: 'REBAR',
    skill_level: 3,
    career_years: 5,
    age: 29,
    region: '부산 사하구',
    desired_daily_wage: 160000,
    certifications: ['건설기능사'],
    completed_count: 28,
    no_show_count: 1,
    current_crew_id: null,
    state_changed_at: '2026-07-11T07:00:00Z',
    created_at: '2026-03-10T09:00:00Z',
    updated_at: '2026-07-11T07:00:00Z',
  },
  {
    worker_id: 'W003',
    user_id: 'USER_WORKER_003',
    name: '이영희',
    phone: '010-3456-7890',
    office_id: 'OFFICE001',
    state: 'READY',
    trade: 'GENERAL',
    skill_level: 4,
    career_years: 10,
    age: 41,
    region: '부산 동래구',
    desired_daily_wage: 150000,
    certifications: ['안전교육이수'],
    completed_count: 56,
    no_show_count: 0,
    current_crew_id: null,
    state_changed_at: '2026-07-11T06:30:00Z',
    created_at: '2026-02-01T09:00:00Z',
    updated_at: '2026-07-11T06:30:00Z',
  },
  {
    worker_id: 'W004',
    user_id: 'USER_WORKER_004',
    name: '최민수',
    phone: '010-4567-8901',
    office_id: 'OFFICE001',
    state: 'READY',
    trade: 'MASONRY',
    skill_level: 5,
    career_years: 15,
    age: 48,
    region: '부산 수영구',
    desired_daily_wage: 200000,
    certifications: ['건설기능사', '특급기능사', '안전교육이수'],
    completed_count: 120,
    no_show_count: 0,
    current_crew_id: null,
    state_changed_at: '2026-07-11T07:30:00Z',
    created_at: '2025-11-01T09:00:00Z',
    updated_at: '2026-07-11T07:30:00Z',
  },
  {
    worker_id: 'W005',
    user_id: 'USER_WORKER_005',
    name: '정대호',
    phone: '010-5678-9012',
    office_id: 'OFFICE001',
    state: 'RUNNING',
    trade: 'FORMWORK',
    skill_level: 3,
    career_years: 4,
    age: 27,
    region: '부산 남구',
    desired_daily_wage: 170000,
    certifications: ['건설기능사'],
    completed_count: 18,
    no_show_count: 2,
    current_crew_id: 'CREW001',
    state_changed_at: '2026-07-12T07:00:00Z',
    created_at: '2026-04-01T09:00:00Z',
    updated_at: '2026-07-12T07:00:00Z',
  },
  {
    worker_id: 'W006',
    user_id: 'USER_WORKER_006',
    name: '한승우',
    phone: '010-6789-0123',
    office_id: 'OFFICE001',
    state: 'READY',
    trade: 'MATERIAL_CARRY',
    skill_level: 2,
    career_years: 2,
    age: 24,
    region: '부산 해운대구',
    desired_daily_wage: 140000,
    certifications: ['안전교육이수'],
    completed_count: 10,
    no_show_count: 0,
    current_crew_id: null,
    state_changed_at: '2026-07-11T08:00:00Z',
    created_at: '2026-05-20T09:00:00Z',
    updated_at: '2026-07-11T08:00:00Z',
  },
];

// 시드 요청 데이터
const SEED_REQUESTS: WorkRequest[] = [
  {
    request_id: 'REQ001',
    company_id: 'USER_COMPANY_001',
    office_id: 'OFFICE001',
    site_name: '해운대 A현장',
    work_date: '2026-07-14',
    start_time: '07:00',
    location_text: '부산 해운대구 우동 123-4',
    required_workers: [
      { trade: 'FORMWORK' as Trade, count: 2 },
      { trade: 'GENERAL' as Trade, count: 1 },
    ],
    budget: 500000,
    priority: { cost: 'MEDIUM', skill: 'HIGH', teamwork: 'MEDIUM' },
    notes: '고층 작업 경험자 우대',
    status: 'RUNNING',
    created_at: '2026-07-10T09:00:00Z',
    updated_at: '2026-07-12T07:00:00Z',
  },
];

export const mockState: MockState = {
  workers: [...SEED_WORKERS],
  requests: [...SEED_REQUESTS],
  crews: [
    {
      crew_id: 'CREW001',
      request_id: 'REQ001',
      office_id: 'OFFICE001',
      status: 'RUNNING',
      source: 'MANUAL',
      member_ids: ['W005'],
      members: [
        {
          worker_id: 'W005',
          name: '정대호',
          trade: 'FORMWORK',
          skill_level: 3,
          desired_daily_wage: 170000,
        },
      ],
      created_at: '2026-07-11T10:00:00Z',
      updated_at: '2026-07-12T07:00:00Z',
    },
  ],
  gapEvents: [],
  notifications: [],
};

// 상태 리셋 (데모용)
export function resetMockState() {
  mockState.workers = [...SEED_WORKERS];
  mockState.requests = [...SEED_REQUESTS];
  mockState.crews = [];
  mockState.gapEvents = [];
  mockState.notifications = [];
}

// 유틸: 현재 로그인 유저 ID 추적
let currentUserId: string | null = null;
export function setCurrentUserId(id: string | null) {
  currentUserId = id;
}
export function getCurrentUserId(): string | null {
  return currentUserId;
}
