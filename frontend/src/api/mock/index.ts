import type {
  ApiResponse,
  LoginRequest,
  LoginResponse,
  Worker,
  WorkRequest,
  WorkerApplicationRequest,
  CreateWorkRequestPayload,
  Crew,
  CrewMember,
  Trade,
} from '../types';
import { SEED_ACCOUNTS, mockState, setCurrentUserId, getCurrentUserId } from './state';

export const handlers: Record<string, (body?: unknown, pathParam?: string) => Promise<ApiResponse<unknown>>> = {
  // === 인증 ===
  'POST /auth/login': async (body) => {
    const { username, password } = body as LoginRequest;
    const account = SEED_ACCOUNTS[username];
    if (!account || account.password !== password) {
      return { success: false, error: { code: 'UNAUTHORIZED', message: '아이디 또는 비밀번호가 일치하지 않습니다.' } };
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
    if (!worker) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    return { success: true, data: worker };
  },

  'POST /worker/application': async (body) => {
    await delay(200);
    const userId = getCurrentUserId();
    const payload = body as WorkerApplicationRequest;
    const existingIdx = mockState.workers.findIndex((w) => w.user_id === userId);

    if (existingIdx >= 0) {
      const existing = mockState.workers[existingIdx];
      mockState.workers[existingIdx] = { ...existing, ...applyApplicationFields(payload), updated_at: new Date().toISOString() };
      return { success: true, data: mockState.workers[existingIdx] };
    }

    const newWorker: Worker = {
      worker_id: `W${String(mockState.workers.length + 1).padStart(3, '0')}`,
      user_id: userId!,
      state: 'INACTIVE',
      completed_count: 0,
      no_show_count: 0,
      current_crew_id: null,
      current_offer: null,
      work_history: [],
      state_changed_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      ...applyApplicationFields(payload),
    };
    mockState.workers.push(newWorker);
    return { success: true, data: newWorker };
  },

  'PUT /worker/application': async (body) => {
    await delay(200);
    const userId = getCurrentUserId();
    const payload = body as WorkerApplicationRequest;
    const idx = mockState.workers.findIndex((w) => w.user_id === userId);
    if (idx < 0) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    mockState.workers[idx] = { ...mockState.workers[idx], ...applyApplicationFields(payload), updated_at: new Date().toISOString() };
    return { success: true, data: mockState.workers[idx] };
  },

  'POST /worker/state/ready': async () => {
    await delay(200);
    const userId = getCurrentUserId();
    const idx = mockState.workers.findIndex((w) => w.user_id === userId);
    if (idx < 0) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    const worker = mockState.workers[idx];
    if (worker.state !== 'INACTIVE') return { success: false, error: { code: 'WORKER_NOT_READY', message: '대기 시작은 INACTIVE 상태에서만 가능합니다.' } };
    mockState.workers[idx] = { ...worker, state: 'READY', state_changed_at: now(), updated_at: now() };
    return { success: true, data: mockState.workers[idx] };
  },

  'POST /worker/state/inactive': async () => {
    await delay(200);
    const userId = getCurrentUserId();
    const idx = mockState.workers.findIndex((w) => w.user_id === userId);
    if (idx < 0) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    const worker = mockState.workers[idx];
    if (worker.state === 'RESERVED' || worker.state === 'RUNNING' || worker.state === 'NOTIFIED') {
      return { success: false, error: { code: 'WORKER_ALREADY_RUNNING', message: '현재 상태에서는 대기를 취소할 수 없습니다.' } };
    }
    mockState.workers[idx] = { ...worker, state: 'INACTIVE', state_changed_at: now(), updated_at: now() };
    return { success: true, data: mockState.workers[idx] };
  },

  // 수락
  'POST /worker/offer/accept': async () => {
    await delay(200);
    const userId = getCurrentUserId();
    const idx = mockState.workers.findIndex((w) => w.user_id === userId);
    if (idx < 0) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    const worker = mockState.workers[idx];
    if (worker.state !== 'NOTIFIED' || !worker.current_offer) {
      return { success: false, error: { code: 'STATE_CONFLICT', message: '수락할 배정 제안이 없습니다.' } };
    }

    // worker → RESERVED
    mockState.workers[idx] = { ...worker, state: 'RESERVED', state_changed_at: now(), updated_at: now() };

    // crew member acceptance 업데이트
    const crew = mockState.crews.find((c) => c.crew_id === worker.current_offer!.crew_id);
    if (crew) {
      const mIdx = crew.members.findIndex((m) => m.worker_id === worker.worker_id);
      if (mIdx >= 0) crew.members[mIdx].acceptance = 'ACCEPTED';

      // 전원 수락 확인 → DISPATCHED
      const allAccepted = crew.members.every((m) => m.acceptance === 'ACCEPTED');
      if (allAccepted) {
        crew.status = 'DISPATCHED';
        crew.updated_at = now();
        // 요청 상태도 변경
        const reqIdx = mockState.requests.findIndex((r) => r.request_id === crew.request_id);
        if (reqIdx >= 0) { mockState.requests[reqIdx].status = 'DISPATCHED'; mockState.requests[reqIdx].updated_at = now(); }
        // 알림: office + company
        pushNotification('USER_OFFICE_001', 'DISPATCH_COMPLETE', '배차 완료', `${crew.crew_id} 작업조 전원이 수락했습니다.`);
        pushNotification('USER_COMPANY_001', 'DISPATCH_COMPLETE', '배차 완료', `요청한 인력이 모두 확정되었습니다.`);
      }
    }

    return { success: true, data: mockState.workers[idx] };
  },

  // 거절
  'POST /worker/offer/decline': async () => {
    await delay(200);
    const userId = getCurrentUserId();
    const idx = mockState.workers.findIndex((w) => w.user_id === userId);
    if (idx < 0) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    const worker = mockState.workers[idx];
    if (worker.state !== 'NOTIFIED' || !worker.current_offer) {
      return { success: false, error: { code: 'STATE_CONFLICT', message: '거절할 배정 제안이 없습니다.' } };
    }

    // worker → READY (다시 대기)
    mockState.workers[idx] = { ...worker, state: 'READY', current_offer: null, current_crew_id: null, state_changed_at: now(), updated_at: now() };

    // crew member acceptance → DECLINED
    const crew = mockState.crews.find((c) => c.crew_id === worker.current_offer!.crew_id);
    if (crew) {
      const mIdx = crew.members.findIndex((m) => m.worker_id === worker.worker_id);
      if (mIdx >= 0) crew.members[mIdx].acceptance = 'DECLINED';
      crew.updated_at = now();

      // office에 거절 알림
      pushNotification('USER_OFFICE_001', 'WORKER_DECLINED', '배정 거절', `${worker.name}님이 배정을 거절했습니다. 재편성이 필요합니다.`);
    }

    return { success: true, data: mockState.workers[idx] };
  },

  'GET /worker/assignments': async () => {
    await delay(150);
    const userId = getCurrentUserId();
    const worker = mockState.workers.find((w) => w.user_id === userId);
    if (!worker || !worker.current_crew_id) return { success: true, data: [] };
    const crew = mockState.crews.find((c) => c.crew_id === worker.current_crew_id);
    if (!crew) return { success: true, data: [] };
    const request = mockState.requests.find((r) => r.request_id === crew.request_id);
    if (!request) return { success: true, data: [] };
    return { success: true, data: [{ crew_id: crew.crew_id, request_id: request.request_id, site_name: request.site_name, work_date: request.work_date, start_time: request.start_time, location_text: request.location_text, status: crew.status }] };
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
      created_at: now(),
      updated_at: now(),
    };
    mockState.requests.push(newRequest);
    return { success: true, data: newRequest };
  },

  'GET /company/requests': async () => {
    await delay(150);
    const userId = getCurrentUserId();
    return { success: true, data: mockState.requests.filter((r) => r.company_id === userId) };
  },

  'GET /company/requests/{id}': async (_body, requestId?: string) => {
    await delay(150);
    const request = mockState.requests.find((r) => r.request_id === requestId);
    if (!request) return { success: false, error: { code: 'REQUEST_NOT_FOUND', message: '요청을 찾을 수 없습니다.' } };
    const crew = mockState.crews.find((c) => c.request_id === request.request_id);
    // member에 실시간 worker_state 추가
    const crewWithState = crew ? {
      ...crew,
      members: crew.members.map((m) => {
        const w = mockState.workers.find((x) => x.worker_id === m.worker_id);
        return { ...m, worker_state: w?.state || 'INACTIVE' };
      }),
    } : null;
    return { success: true, data: { ...request, crew: crewWithState } };
  },

  // 출근 처리 (company가 호출)
  'POST /company/crews/{crewId}/checkin/{workerId}': async (_body, _crewId?: string) => {
    await delay(200);
    // crewId에서 실제로는 crewId/checkin/workerId 형태로 올 수 있지만 단순화
    // body로 worker_id 전달
    const { worker_id } = (_body || {}) as { worker_id: string };
    const wIdx = mockState.workers.findIndex((w) => w.worker_id === worker_id);
    if (wIdx < 0) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자를 찾을 수 없습니다.' } };
    const worker = mockState.workers[wIdx];
    if (worker.state !== 'RESERVED') return { success: false, error: { code: 'STATE_CONFLICT', message: '출근 처리는 배차완료(RESERVED) 상태에서만 가능합니다.' } };
    mockState.workers[wIdx] = { ...worker, state: 'RUNNING', state_changed_at: now(), updated_at: now() };
    // crew도 RUNNING으로 변경 (전원 RUNNING 시)
    const crew = mockState.crews.find((c) => c.crew_id === worker.current_crew_id);
    if (crew) {
      const allRunning = crew.member_ids.every((id) => {
        const w = mockState.workers.find((x) => x.worker_id === id);
        return w && w.state === 'RUNNING';
      });
      if (allRunning) { crew.status = 'RUNNING'; crew.updated_at = now(); }
    }
    return { success: true, data: mockState.workers[wIdx] };
  },

  // 퇴근 처리 (company가 호출)
  'POST /company/crews/{crewId}/checkout/{workerId}': async (_body) => {
    await delay(200);
    const { worker_id } = (_body || {}) as { worker_id: string };
    const wIdx = mockState.workers.findIndex((w) => w.worker_id === worker_id);
    if (wIdx < 0) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자를 찾을 수 없습니다.' } };
    const worker = mockState.workers[wIdx];
    if (worker.state !== 'RUNNING') return { success: false, error: { code: 'STATE_CONFLICT', message: '퇴근 처리는 작업중(RUNNING) 상태에서만 가능합니다.' } };
    const crewIdBeforeCheckout = worker.current_crew_id;
    const crewForHistory = mockState.crews.find((c) => c.crew_id === crewIdBeforeCheckout);
    const reqForHistory = crewForHistory ? mockState.requests.find((r) => r.request_id === crewForHistory.request_id) : null;
    const memberForHistory = crewForHistory?.members.find((m) => m.worker_id === worker_id);
    const historyEntry = reqForHistory && memberForHistory ? {
      crew_id: crewIdBeforeCheckout!,
      request_id: reqForHistory.request_id,
      site_name: reqForHistory.site_name,
      work_date: reqForHistory.work_date,
      assigned_trade: memberForHistory.assigned_trade,
      offered_wage: memberForHistory.offered_wage,
      completed_at: now(),
    } : null;
    mockState.workers[wIdx] = { ...worker, state: 'INACTIVE', current_crew_id: null, current_offer: null, completed_count: worker.completed_count + 1, work_history: historyEntry ? [...worker.work_history, historyEntry] : worker.work_history, state_changed_at: now(), updated_at: now() };
    // 전원 퇴근(INACTIVE) 시 crew→COMPLETED, request→COMPLETED
    const crew = mockState.crews.find((c) => c.crew_id === crewIdBeforeCheckout);
    if (crew) {
      const allDone = crew.member_ids.every((id) => {
        if (id === worker_id) return true; // 방금 퇴근한 worker
        const w = mockState.workers.find((x) => x.worker_id === id);
        return w && w.state === 'INACTIVE';
      });
      if (allDone) {
        crew.status = 'COMPLETED'; crew.updated_at = now();
        const reqIdx = mockState.requests.findIndex((r) => r.request_id === crew.request_id);
        if (reqIdx >= 0) { mockState.requests[reqIdx].status = 'COMPLETED'; mockState.requests[reqIdx].updated_at = now(); }
      }
    }
    return { success: true, data: mockState.workers[wIdx] };
  },

  // === 사무소 API ===
  'GET /office/workers': async () => {
    await delay(150);
    return { success: true, data: mockState.workers.filter((w) => w.office_id === 'OFFICE001') };
  },

  'GET /office/requests': async () => {
    await delay(150);
    return { success: true, data: mockState.requests.filter((r) => r.office_id === 'OFFICE001') };
  },

  'GET /office/requests/{id}': async (_body, requestId?: string) => {
    await delay(150);
    const request = mockState.requests.find((r) => r.request_id === requestId);
    if (!request) return { success: false, error: { code: 'REQUEST_NOT_FOUND', message: '요청을 찾을 수 없습니다.' } };
    const crew = mockState.crews.find((c) => c.request_id === request.request_id);
    const crewWithState = crew ? {
      ...crew,
      members: crew.members.map((m) => {
        const w = mockState.workers.find((x) => x.worker_id === m.worker_id);
        return { ...m, worker_state: w?.state || 'INACTIVE' };
      }),
    } : null;
    return { success: true, data: { ...request, crew: crewWithState } };
  },

  // office가 요청 거절
  'POST /office/requests/{requestId}/reject': async (body, requestId?: string) => {
    await delay(200);
    const { reason } = (body || {}) as { reason: string };
    const reqIdx = mockState.requests.findIndex((r) => r.request_id === requestId);
    if (reqIdx < 0) return { success: false, error: { code: 'REQUEST_NOT_FOUND', message: '요청을 찾을 수 없습니다.' } };
    const req = mockState.requests[reqIdx];
    if (req.status !== 'REQUESTED') return { success: false, error: { code: 'STATE_CONFLICT', message: '이미 처리된 요청입니다.' } };
    mockState.requests[reqIdx] = { ...req, status: 'REJECTED', rejection_reason: reason, updated_at: now() };
    pushNotification(req.company_id, 'REQUEST_REJECTED', '요청 거절', `"${req.site_name}" 요청이 거절되었습니다. 사유: ${reason}`);
    return { success: true, data: mockState.requests[reqIdx] };
  },

  // office가 무응답 worker 제안 취소 (worker→INACTIVE)
  'POST /office/crews/{crewId}/cancel-offer/{workerId}': async (body, _param?: string) => {
    await delay(200);
    const { worker_id } = (body || {}) as { worker_id: string };
    const wIdx = mockState.workers.findIndex((w) => w.worker_id === worker_id);
    if (wIdx < 0) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자를 찾을 수 없습니다.' } };
    const worker = mockState.workers[wIdx];
    if (worker.state !== 'NOTIFIED') return { success: false, error: { code: 'STATE_CONFLICT', message: '제안 취소는 NOTIFIED 상태에서만 가능합니다.' } };
    mockState.workers[wIdx] = { ...worker, state: 'INACTIVE', current_offer: null, current_crew_id: null, state_changed_at: now(), updated_at: now() };
    // crew member → DECLINED 처리
    const crew = mockState.crews.find((c) => c.crew_id === worker.current_crew_id || c.member_ids.includes(worker_id));
    if (crew) {
      const mIdx = crew.members.findIndex((m) => m.worker_id === worker_id);
      if (mIdx >= 0) crew.members[mIdx].acceptance = 'DECLINED';
      crew.updated_at = now();
    }
    pushNotification(worker.user_id, 'OFFER_CANCELLED', '제안 취소', '배정 제안이 취소되었습니다.');
    return { success: true, data: mockState.workers[wIdx] };
  },

  // worker 작업 이력 조회
  'GET /worker/history': async () => {
    await delay(150);
    const userId = getCurrentUserId();
    const worker = mockState.workers.find((w) => w.user_id === userId);
    if (!worker) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: '근로자 정보를 찾을 수 없습니다.' } };
    return { success: true, data: worker.work_history };
  },

  // 수동 편성 (새 플로우: assigned_trade + offered_wage 포함)
  'POST /office/crews/manual': async (body) => {
    await delay(300);
    const { request_id, members: memberInputs } = body as {
      request_id: string;
      members: { worker_id: string; assigned_trade: Trade; offered_wage: number }[];
    };

    const request = mockState.requests.find((r) => r.request_id === request_id);
    if (!request) return { success: false, error: { code: 'REQUEST_NOT_FOUND', message: '요청을 찾을 수 없습니다.' } };

    // 검증: 비희망 직종 배정 불가
    for (const mi of memberInputs) {
      const w = mockState.workers.find((x) => x.worker_id === mi.worker_id);
      if (!w) return { success: false, error: { code: 'WORKER_NOT_FOUND', message: `${mi.worker_id}를 찾을 수 없습니다.` } };
      if (w.state !== 'READY') return { success: false, error: { code: 'WORKER_NOT_READY', message: `${w.name}님은 READY 상태가 아닙니다.` } };
      if (w.excluded_trades.includes(mi.assigned_trade)) {
        return { success: false, error: { code: 'CREW_INVALID', message: `${w.name}님은 ${mi.assigned_trade} 직종을 희망하지 않습니다.` } };
      }
    }

    // 직종별 인원 검증
    const tradeCount: Record<string, number> = {};
    for (const mi of memberInputs) { tradeCount[mi.assigned_trade] = (tradeCount[mi.assigned_trade] || 0) + 1; }
    for (const req of request.required_workers) {
      if ((tradeCount[req.trade] || 0) < req.count) {
        return { success: false, error: { code: 'CREW_INVALID', message: `${req.trade} 직종이 부족합니다.` } };
      }
    }

    const crewMembers: CrewMember[] = memberInputs.map((mi) => {
      const w = mockState.workers.find((x) => x.worker_id === mi.worker_id)!;
      return { worker_id: w.worker_id, name: w.name, assigned_trade: mi.assigned_trade, skill_level: w.skill_level, offered_wage: mi.offered_wage, acceptance: 'PENDING' };
    });

    const newCrew: Crew = {
      crew_id: `CREW${String(mockState.crews.length + 1).padStart(3, '0')}`,
      request_id,
      office_id: 'OFFICE001',
      status: 'DRAFT',
      source: 'MANUAL',
      member_ids: memberInputs.map((m) => m.worker_id),
      members: crewMembers,
      created_at: now(),
      updated_at: now(),
    };
    mockState.crews.push(newCrew);
    return { success: true, data: newCrew };
  },

  // 승인 → NOTIFIED (새 플로우: worker에게 제안 전송)
  'POST /office/crews/{crewId}/approve': async (_body, crewId?: string) => {
    await delay(400);
    const crewIdx = mockState.crews.findIndex((c) => c.crew_id === crewId);
    if (crewIdx < 0) return { success: false, error: { code: 'CREW_INVALID', message: '작업조를 찾을 수 없습니다.' } };
    const crew = mockState.crews[crewIdx];

    // 전원 READY 재검증
    for (const memberId of crew.member_ids) {
      const w = mockState.workers.find((x) => x.worker_id === memberId);
      if (!w || w.state !== 'READY') {
        return { success: false, error: { code: 'STATE_CONFLICT', message: '일부 근로자가 이미 다른 작업에 배정되었습니다.' } };
      }
    }

    const request = mockState.requests.find((r) => r.request_id === crew.request_id);

    // worker 상태 → NOTIFIED + current_offer 세팅
    for (const member of crew.members) {
      const wIdx = mockState.workers.findIndex((x) => x.worker_id === member.worker_id);
      if (wIdx >= 0) {
        mockState.workers[wIdx] = {
          ...mockState.workers[wIdx],
          state: 'NOTIFIED',
          current_crew_id: crew.crew_id,
          current_offer: {
            crew_id: crew.crew_id,
            assigned_trade: member.assigned_trade,
            offered_wage: member.offered_wage,
            site_name: request?.site_name || '',
            work_date: request?.work_date || '',
            start_time: request?.start_time || '',
            location_text: request?.location_text || '',
          },
          state_changed_at: now(),
          updated_at: now(),
        };
        pushNotification(mockState.workers[wIdx].user_id, 'OFFER', '배정 제안', `${request?.site_name}에 배정 제안이 도착했습니다. 확인 후 수락해주세요.`);
      }
    }

    // crew → NOTIFIED, request → APPROVED
    mockState.crews[crewIdx] = { ...crew, status: 'NOTIFIED', updated_at: now() };
    if (request) {
      const reqIdx = mockState.requests.findIndex((r) => r.request_id === request.request_id);
      if (reqIdx >= 0) mockState.requests[reqIdx] = { ...mockState.requests[reqIdx], status: 'APPROVED', updated_at: now() };
    }

    return { success: true, data: mockState.crews[crewIdx] };
  },

  // === 공통 ===
  'GET /notifications': async () => {
    await delay(100);
    const userId = getCurrentUserId();
    return { success: true, data: mockState.notifications.filter((n) => n.user_id === userId) };
  },
};

// === 헬퍼 ===
function delay(ms: number) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function now() { return new Date().toISOString(); }

function applyApplicationFields(payload: WorkerApplicationRequest) {
  return {
    name: payload.name,
    phone: payload.phone,
    office_id: payload.office_id,
    preferred_trades: payload.preferred_trades,
    excluded_trades: payload.excluded_trades,
    skill_level: payload.skill_level,
    career_years: payload.career_years,
    age: payload.age,
    region: payload.region,
    desired_daily_wage: payload.desired_daily_wage,
    certifications: payload.certifications,
  };
}

function pushNotification(userId: string, type: string, title: string, message: string) {
  mockState.notifications.push({
    id: `NOTI_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    user_id: userId,
    type,
    title,
    message,
    read: false,
    created_at: now(),
  });
}
