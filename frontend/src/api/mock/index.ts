import type {
  ApiResponse,
  LoginRequest,
  LoginResponse,
  Worker,
  WorkRequest,
  WorkerApplicationRequest,
  CreateWorkRequestPayload,
} from '../types';
import { SEED_ACCOUNTS, mockState, setCurrentUserId, getCurrentUserId } from './state';

// mock 핸들러 레지스트리
export const handlers: Record<string, (body?: unknown) => Promise<ApiResponse<unknown>>> = {
  // === 인증 ===
  'POST /auth/login': async (body) => {
    const { username, password } = body as LoginRequest;
    const account = SEED_ACCOUNTS[username];

    if (!account || account.password !== password) {
      return {
        success: false,
        error: { code: 'UNAUTHORIZED', message: '아이디 또는 비밀번호가 일치하지 않습니다.' },
      };
    }

    await delay(300);
    setCurrentUserId(account.user.userId);

    const response: LoginResponse = { user: account.user };
    return { success: true, data: response };
  },

  // === 근로자 API ===
  'GET /worker/me': async () => {
    await delay(150);
    const userId = getCurrentUserId();
    const worker = mockState.workers.find((w) => w.user_id === userId);

    if (!worker) {
      return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    }

    return { success: true, data: worker };
  },

  'POST /worker/application': async (body) => {
    await delay(200);
    const userId = getCurrentUserId();
    const payload = body as WorkerApplicationRequest;

    // 기존 근로자 있으면 업데이트, 없으면 신규 생성
    const existingIdx = mockState.workers.findIndex((w) => w.user_id === userId);

    if (existingIdx >= 0) {
      // 업데이트
      const existing = mockState.workers[existingIdx];
      mockState.workers[existingIdx] = {
        ...existing,
        name: payload.name,
        phone: payload.phone,
        office_id: payload.office_id,
        trade: payload.trade,
        skill_level: payload.skill_level,
        career_years: payload.career_years,
        age: payload.age,
        region: payload.region,
        desired_daily_wage: payload.desired_daily_wage,
        certifications: payload.certifications,
        updated_at: new Date().toISOString(),
      };
      return { success: true, data: mockState.workers[existingIdx] };
    }

    // 신규 생성
    const newWorker: Worker = {
      worker_id: `W${String(mockState.workers.length + 1).padStart(3, '0')}`,
      user_id: userId!,
      name: payload.name,
      phone: payload.phone,
      office_id: payload.office_id,
      state: 'INACTIVE',
      trade: payload.trade,
      skill_level: payload.skill_level,
      career_years: payload.career_years,
      age: payload.age,
      region: payload.region,
      desired_daily_wage: payload.desired_daily_wage,
      certifications: payload.certifications,
      completed_count: 0,
      no_show_count: 0,
      current_crew_id: null,
      state_changed_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    mockState.workers.push(newWorker);
    return { success: true, data: newWorker };
  },

  'PUT /worker/application': async (body) => {
    await delay(200);
    const userId = getCurrentUserId();
    const payload = body as WorkerApplicationRequest;

    const idx = mockState.workers.findIndex((w) => w.user_id === userId);
    if (idx < 0) {
      return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    }

    const existing = mockState.workers[idx];
    mockState.workers[idx] = {
      ...existing,
      name: payload.name,
      phone: payload.phone,
      office_id: payload.office_id,
      trade: payload.trade,
      skill_level: payload.skill_level,
      career_years: payload.career_years,
      age: payload.age,
      region: payload.region,
      desired_daily_wage: payload.desired_daily_wage,
      certifications: payload.certifications,
      updated_at: new Date().toISOString(),
    };

    return { success: true, data: mockState.workers[idx] };
  },

  'POST /worker/state/ready': async () => {
    await delay(200);
    const userId = getCurrentUserId();
    const idx = mockState.workers.findIndex((w) => w.user_id === userId);

    if (idx < 0) {
      return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    }

    const worker = mockState.workers[idx];
    if (worker.state !== 'INACTIVE') {
      return { success: false, error: { code: 'WORKER_NOT_READY', message: '대기 시작은 INACTIVE 상태에서만 가능합니다.' } };
    }

    mockState.workers[idx] = {
      ...worker,
      state: 'READY',
      state_changed_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    return { success: true, data: mockState.workers[idx] };
  },

  'POST /worker/state/inactive': async () => {
    await delay(200);
    const userId = getCurrentUserId();
    const idx = mockState.workers.findIndex((w) => w.user_id === userId);

    if (idx < 0) {
      return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    }

    const worker = mockState.workers[idx];
    if (worker.state === 'RESERVED' || worker.state === 'RUNNING') {
      return { success: false, error: { code: 'WORKER_ALREADY_RUNNING', message: '배정 중이거나 작업 중일 때는 대기를 취소할 수 없습니다.' } };
    }

    mockState.workers[idx] = {
      ...worker,
      state: 'INACTIVE',
      state_changed_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    return { success: true, data: mockState.workers[idx] };
  },

  'GET /worker/assignments': async () => {
    await delay(150);
    const userId = getCurrentUserId();
    const worker = mockState.workers.find((w) => w.user_id === userId);

    if (!worker || !worker.current_crew_id) {
      return { success: true, data: [] };
    }

    const crew = mockState.crews.find((c) => c.crew_id === worker.current_crew_id);
    if (!crew) {
      return { success: true, data: [] };
    }

    const request = mockState.requests.find((r) => r.request_id === crew.request_id);
    if (!request) {
      return { success: true, data: [] };
    }

    return {
      success: true,
      data: [
        {
          crew_id: crew.crew_id,
          request_id: request.request_id,
          site_name: request.site_name,
          work_date: request.work_date,
          start_time: request.start_time,
          location_text: request.location_text,
          status: crew.status,
        },
      ],
    };
  },

  // === 건설사 API ===
  'POST /company/requests': async (body) => {
    await delay(300);
    const userId = getCurrentUserId();
    const payload = body as CreateWorkRequestPayload;

    const newRequest: WorkRequest = {
      request_id: `REQ${String(mockState.requests.length + 1).padStart(3, '0')}`,
      company_id: userId!,
      office_id: payload.office_id,
      site_name: payload.site_name,
      work_date: payload.work_date,
      start_time: payload.start_time,
      location_text: payload.location_text,
      required_workers: payload.required_workers,
      budget: payload.budget,
      priority: payload.priority,
      notes: payload.notes,
      status: 'REQUESTED',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    mockState.requests.push(newRequest);
    return { success: true, data: newRequest };
  },

  'GET /company/requests': async () => {
    await delay(150);
    const userId = getCurrentUserId();
    const myRequests = mockState.requests.filter((r) => r.company_id === userId);
    return { success: true, data: myRequests };
  },

  'GET /company/requests/{id}': async (_body, requestId?: string) => {
    await delay(150);
    const request = mockState.requests.find((r) => r.request_id === requestId);

    if (!request) {
      return { success: false, error: { code: 'REQUEST_NOT_FOUND', message: '요청을 찾을 수 없습니다.' } };
    }

    // 작업조 정보도 함께 반환
    const crew = mockState.crews.find((c) => c.request_id === request.request_id);

    return { success: true, data: { ...request, crew: crew || null } };
  },

  // === 사무소 API (Day3 준비) ===
  'GET /office/workers': async () => {
    await delay(150);
    return { success: true, data: mockState.workers };
  },

  // === 공통 ===
  'GET /notifications': async () => {
    await delay(100);
    const userId = getCurrentUserId();
    const myNotifications = mockState.notifications.filter((n) => n.user_id === userId);
    return { success: true, data: myNotifications };
  },
};

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
