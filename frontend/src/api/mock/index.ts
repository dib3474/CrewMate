import type { ApiResponse, LoginRequest, LoginResponse } from '../types';
import { SEED_ACCOUNTS } from './state';

// mock 핸들러 레지스트리
// key: "METHOD /path"
// value: (body?) => Promise<ApiResponse>
export const handlers: Record<string, (body?: unknown) => Promise<ApiResponse<unknown>>> = {
  'POST /auth/login': async (body) => {
    const { username, password } = body as LoginRequest;
    const account = SEED_ACCOUNTS[username];

    if (!account || account.password !== password) {
      return {
        success: false,
        error: { code: 'UNAUTHORIZED', message: '아이디 또는 비밀번호가 일치하지 않습니다.' },
      };
    }

    // 로그인 성공 시 약간의 딜레이 시뮬레이션
    await delay(300);

    const response: LoginResponse = { user: account.user };
    return { success: true, data: response };
  },

  'GET /notifications': async () => {
    await delay(100);
    return { success: true, data: [] };
  },

  'GET /worker/me': async () => {
    await delay(100);
    return {
      success: true,
      data: {
        worker_id: 'W001',
        name: '김건우',
        state: 'INACTIVE',
        trade: 'FORMWORK',
        skill_level: 4,
        office_id: 'OFFICE001',
      },
    };
  },
};

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
