import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import LoginPage from './auth/LoginPage';
import RoleGuard from './auth/RoleGuard';
import Layout from './components/Layout';

// Worker pages
import WorkerHomePage from './pages/worker/HomePage';
import WorkerApplicationPage from './pages/worker/ApplicationPage';
import WorkerAssignmentsPage from './pages/worker/AssignmentsPage';

// Office pages
import OfficeHomePage from './pages/office/HomePage';
import OfficeWorkersPage from './pages/office/WorkersPage';
import OfficeRequestDetailPage from './pages/office/RequestDetailPage';
import OfficeComposePage from './pages/office/ComposePage';

// Company pages
import CompanyHomePage from './pages/company/HomePage';
import CompanyCreateRequestPage from './pages/company/CreateRequestPage';
import CompanyRequestDetailPage from './pages/company/RequestDetailPage';

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
            <Route path="application" element={<WorkerApplicationPage />} />
            <Route path="assignments" element={<WorkerAssignmentsPage />} />
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
            <Route path="workers" element={<OfficeWorkersPage />} />
            <Route path="requests/:requestId" element={<OfficeRequestDetailPage />} />
            <Route path="compose/:requestId" element={<OfficeComposePage />} />
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
            <Route path="requests/new" element={<CompanyCreateRequestPage />} />
            <Route path="requests/:requestId" element={<CompanyRequestDetailPage />} />
          </Route>

          {/* 기본 리다이렉트 */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
