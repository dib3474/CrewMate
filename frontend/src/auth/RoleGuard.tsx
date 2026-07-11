import { Navigate } from 'react-router-dom';
import { useAuth } from './AuthContext';
import type { UserRole } from '../api/types';

interface RoleGuardProps {
  allowedRole: UserRole;
  children: React.ReactNode;
}

const ROLE_HOME: Record<UserRole, string> = {
  WORKER: '/worker',
  OFFICE: '/office',
  COMPANY: '/company',
};

export default function RoleGuard({ allowedRole, children }: RoleGuardProps) {
  const { user, isAuthenticated } = useAuth();

  // 미인증 → 로그인 페이지
  if (!isAuthenticated || !user) {
    return <Navigate to="/login" replace />;
  }

  // 역할 불일치 → 자기 홈으로 리다이렉트
  if (user.role !== allowedRole) {
    return <Navigate to={ROLE_HOME[user.role]} replace />;
  }

  return <>{children}</>;
}
