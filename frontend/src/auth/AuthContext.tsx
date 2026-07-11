import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import type { AuthUser, LoginRequest } from '../api/types';
import { api, setAuthToken } from '../api/client';

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  login: (credentials: LoginRequest) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);

  const login = useCallback(async (credentials: LoginRequest) => {
    const res = await api.post<{ user: AuthUser }>('/auth/login', credentials);

    if (res.success) {
      const authUser = res.data.user;
      setUser(authUser);
      setAuthToken(authUser.token);
      return { success: true };
    } else {
      return { success: false, error: res.error.message };
    }
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    setAuthToken(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isAuthenticated: !!user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
