import type {
  AuthUser,
  Worker,
  WorkRequest,
  Crew,
  GapEvent,
  Notification,
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

export const mockState: MockState = {
  workers: [],
  requests: [],
  crews: [],
  gapEvents: [],
  notifications: [],
};
