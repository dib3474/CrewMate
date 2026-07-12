import type {
  ApiResponse,
  LoginRequest,
  LoginResponse,
  Worker,
  WorkRequest,
  WorkerApplicationRequest,
  CreateWorkRequestPayload,
  Crew,
} from '../types';
import { SEED_ACCOUNTS, mockState, setCurrentUserId, getCurrentUserId } from './state';

// mock 핸들러 레지스트리
export const handlers: Record<string, (body?: unknown, pathParam?: string) => Promise<ApiResponse<unknown>>> = {
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

    const existingIdx = mockState.workers.findIndex((w) => w.user_id === userId);

    if (existingIdx >= 0) {
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

    mockState.workers[idx] = { ...worker, state: 'READY', state_changed_at: new Date().toISOString(), updated_at: new Date().toISOString() };
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

    mockState.workers[idx] = { ...worker, state: 'INACTIVE', state_changed_at: new Date().toISOString(), updated_at: new Date().toISOString() };
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
    if (!crew) return { success: true, data: [] };

    const request = mockState.requests.find((r) => r.request_id === crew.request_id);
    if (!request) return { success: true, data: [] };

    return {
      success: true,
      data: [{
        crew_id: crew.crew_id,
        request_id: request.request_id,
        site_name: request.site_name,
        work_date: request.work_date,
        start_time: request.start_time,
        location_text: request.location_text,
        status: crew.status,
      }],
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
    const crew = mockState.crews.find((c) => c.request_id === request.request_id);
    return { success: true, data: { ...request, crew: crew || null } };
  },

  // === 사무소 API ===
  'GET /office/workers': async () => {
    await delay(150);
    // 사무소 소속 근로자만 반환 (OFFICE001 고정)
    const workers = mockState.workers.filter((w) => w.office_id === 'OFFICE001');
    return { success: true, data: workers };
  },

  'GET /office/requests': async () => {
    await delay(150);
    // 이 사무소로 들어온 요청만
    const requests = mockState.requests.filter((r) => r.office_id === 'OFFICE001');
    return { success: true, data: requests };
  },

  'GET /office/requests/{id}': async (_body, requestId?: string) => {
    await delay(150);
    const request = mockState.requests.find((r) => r.request_id === requestId);
    if (!request) {
      return { success: false, error: { code: 'REQUEST_NOT_FOUND', message: '요청을 찾을 수 없습니다.' } };
    }
    const crew = mockState.crews.find((c) => c.request_id === request.request_id);
    return { success: true, data: { ...request, crew: crew || null } };
  },

  'POST /office/crews/manual': async (body) => {
    await delay(300);
    const { request_id, member_ids } = body as { request_id: string; member_ids: string[] };

    const request = mockState.requests.find((r) => r.request_id === request_id);
    if (!request) {
      return { success: false, error: { code: 'REQUEST_NOT_FOUND', message: '요청을 찾을 수 없습니다.' } };
    }

    // 직종별 필수 인원 검증
    const selectedWorkers = mockState.workers.filter((w) => member_ids.includes(w.worker_id));
    const tradeCount: Record<string, number> = {};
    for (const w of selectedWorkers) {
      tradeCount[w.trade] = (tradeCount[w.trade] || 0) + 1;
    }

    for (const req of request.required_workers) {
      const have = tradeCount[req.trade] || 0;
      if (have < req.count) {
        return {
          success: false,
          error: { code: 'CREW_INVALID', message: `${req.trade} 직종이 ${req.count - have}명 부족합니다.` },
        };
      }
    }

    // 중복 검증
    const uniqueIds = new Set(member_ids);
    if (uniqueIds.size !== member_ids.length) {
      return { success: false, error: { code: 'CREW_INVALID', message: '동일 근로자가 중복 선택되었습니다.' } };
    }

    // READY 검증
    for (const w of selectedWorkers) {
      if (w.state !== 'READY') {
        return { success: false, error: { code: 'WORKER_NOT_READY', message: `${w.name}님은 현재 READY 상태가 아닙니다.` } };
      }
    }

    // 크루 생성 (DRAFT 상태)
    const newCrew: Crew = {
      crew_id: `CREW${String(mockState.crews.length + 1).padStart(3, '0')}`,
      request_id,
      office_id: 'OFFICE001',
      status: 'DRAFT',
      source: 'MANUAL',
      member_ids,
      members: selectedWorkers.map((w) => ({
        worker_id: w.worker_id,
        name: w.name,
        trade: w.trade,
        skill_level: w.skill_level,
        desired_daily_wage: w.desired_daily_wage,
      })),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    mockState.crews.push(newCrew);
    return { success: true, data: newCrew };
  },

  'POST /office/crews/{crewId}/approve': async (_body, crewId?: string) => {
    await delay(400);
    const crewIdx = mockState.crews.findIndex((c) => c.crew_id === crewId);
    if (crewIdx < 0) {
      return { success: false, error: { code: 'CREW_INVALID', message: '작업조를 찾을 수 없습니다.' } };
    }

    const crew = mockState.crews[crewIdx];

    // 조원 전원 READY 상태 재검증 (조건부 쓰기 시뮬레이션)
    for (const memberId of crew.member_ids) {
      const w = mockState.workers.find((x) => x.worker_id === memberId);
      if (!w || w.state !== 'READY') {
        return {
          success: false,
          error: { code: 'STATE_CONFLICT', message: '일부 근로자가 이미 다른 작업에 배정되었습니다. 재편성이 필요합니다.' },
        };
      }
    }

    // TransactWriteItems 시뮬레이션: 전원 READY → RESERVED → RUNNING
    const now = new Date().toISOString();
    for (const memberId of crew.member_ids) {
      const idx = mockState.workers.findIndex((x) => x.worker_id === memberId);
      if (idx >= 0) {
        mockState.workers[idx] = {
          ...mockState.workers[idx],
          state: 'RUNNING',
          current_crew_id: crew.crew_id,
          state_changed_at: now,
          updated_at: now,
        };
      }
    }

    // 크루 상태 업데이트
    mockState.crews[crewIdx] = { ...crew, status: 'RUNNING', updated_at: now };

    // 요청 상태 업데이트
    const reqIdx = mockState.requests.findIndex((r) => r.request_id === crew.request_id);
    if (reqIdx >= 0) {
      mockState.requests[reqIdx] = { ...mockState.requests[reqIdx], status: 'RUNNING', updated_at: now };
    }

    // 알림 생성
    for (const memberId of crew.member_ids) {
      const w = mockState.workers.find((x) => x.worker_id === memberId);
      if (w) {
        const req = mockState.requests.find((r) => r.request_id === crew.request_id);
        mockState.notifications.push({
          id: `NOTI${Date.now()}_${memberId}`,
          user_id: w.user_id,
          type: 'ASSIGNMENT',
          title: '작업 배정 알림',
          message: `${req?.site_name || '현장'}에 배정되었습니다. ${req?.work_date} ${req?.start_time}`,
          read: false,
          created_at: now,
        });
      }
    }

    return { success: true, data: mockState.crews[crewIdx] };
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
