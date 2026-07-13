import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { AuthProvider } from './auth/AuthContext';
import LoginPage from './auth/LoginPage';
import SignupPage from './auth/SignupPage';
import RoleGuard from './auth/RoleGuard';
import Layout from './components/Layout';

// Worker pages
import WorkerHomePage from './pages/worker/HomePage';
import WorkerApplicationPage from './pages/worker/ApplicationPage';
import WorkerAssignmentsPage from './pages/worker/AssignmentsPage';
import WorkerHistoryPage from './pages/worker/HistoryPage';

// Office pages
import OfficeHomePage from './pages/office/HomePage';
import OfficeWorkersPage from './pages/office/WorkersPage';
import OfficeRequestDetailPage from './pages/office/RequestDetailPage';
import OfficeComposePage from './pages/office/ComposePage';
import OfficeEmergencyPage from './pages/office/EmergencyPage';

// Company pages
import CompanyHomePage from './pages/company/HomePage';
import CompanyCreateRequestPage from './pages/company/CreateRequestPage';
import CompanyRequestDetailPage from './pages/company/RequestDetailPage';

export default function App() {
  return (
    <BrowserRouter>
      <Toaster position="top-center" toastOptions={{ duration: 3000 }} />
      <AuthProvider>
        <Routes>
          {/* 로그인 / 회원가입 */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />

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
            <Route path="history" element={<WorkerHistoryPage />} />
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
            <Route path="emergency/:eventId" element={<OfficeEmergencyPage />} />
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
