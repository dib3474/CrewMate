import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import LoginPage from './auth/LoginPage';
import RoleGuard from './auth/RoleGuard';
import Layout from './components/Layout';
import WorkerHomePage from './pages/worker/HomePage';
import OfficeHomePage from './pages/office/HomePage';
import CompanyHomePage from './pages/company/HomePage';

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* 로그인 */}
          <Route path="/login" element={<LoginPage />} />

          {/* 근로자 */}
          <Route
            path="/worker"
            element={
              <RoleGuard allowedRole="WORKER">
                <Layout />
              </RoleGuard>
            }
          >
            <Route index element={<WorkerHomePage />} />
          </Route>

          {/* 인력사무소 */}
          <Route
            path="/office"
            element={
              <RoleGuard allowedRole="OFFICE">
                <Layout />
              </RoleGuard>
            }
          >
            <Route index element={<OfficeHomePage />} />
          </Route>

          {/* 건설사 */}
          <Route
            path="/company"
            element={
              <RoleGuard allowedRole="COMPANY">
                <Layout />
              </RoleGuard>
            }
          >
            <Route index element={<CompanyHomePage />} />
          </Route>

          {/* 기본 리다이렉트 */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
