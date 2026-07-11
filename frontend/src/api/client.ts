import type { ApiResponse } from './types';

const API_MODE = import.meta.env.VITE_API_MODE || 'mock';
const API_URL = import.meta.env.VITE_API_URL || '';

// mock 핸들러를 동적으로 임포트
let mockHandlers: Record<string, (body?: unknown) => Promise<ApiResponse<unknown>>> = {};

async function getMockHandlers() {
  if (Object.keys(mockHandlers).length === 0) {
    const mod = await import('./mock');
    mockHandlers = mod.handlers;
  }
  return mockHandlers;
}

// 인증 토큰 (메모리에만 보관)
let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function getAuthToken(): string | null {
  return authToken;
}

// API 요청 공통 함수
export async function apiRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown
): Promise<ApiResponse<T>> {
  if (API_MODE === 'mock') {
    const handlers = await getMockHandlers();
    const key = `${method} ${path}`;

    // 정확한 매칭 먼저 시도
    if (handlers[key]) {
      return handlers[key](body) as Promise<ApiResponse<T>>;
    }

    // 패턴 매칭 시도 (경로 파라미터)
    for (const [pattern, handler] of Object.entries(handlers)) {
      const regex = patternToRegex(pattern);
      if (regex.test(key)) {
        return handler(body) as Promise<ApiResponse<T>>;
      }
    }

    return {
      success: false,
      error: { code: 'NOT_IMPLEMENTED', message: `Mock not implemented: ${key}` },
    } as ApiResponse<T>;
  }

  // 실 API 호출
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  const response = await fetch(`${API_URL}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  return response.json() as Promise<ApiResponse<T>>;
}

// 경로 패턴을 정규식으로 변환 (예: GET /company/requests/{id} → regex)
function patternToRegex(pattern: string): RegExp {
  const escaped = pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const withParams = escaped.replace(/\\{[^}]+\\}/g, '[^/]+');
  return new RegExp(`^${withParams}$`);
}

// 편의 함수
export const api = {
  get: <T>(path: string) => apiRequest<T>('GET', path),
  post: <T>(path: string, body?: unknown) => apiRequest<T>('POST', path, body),
  put: <T>(path: string, body?: unknown) => apiRequest<T>('PUT', path, body),
  delete: <T>(path: string) => apiRequest<T>('DELETE', path),
};
