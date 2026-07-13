import { useState, type FormEvent } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from './AuthContext';

const ROLE_HOME: Record<string, string> = {
  WORKER: '/worker',
  OFFICE: '/office',
  COMPANY: '/company',
};

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    const result = await login({ username, password });

    if (result.success && result.role) {
      navigate(ROLE_HOME[result.role], { replace: true });
    } else {
      setError(result.error || '로그인에 실패했습니다.');
    }

    setLoading(false);
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-sm p-8 bg-white rounded-xl shadow-md">
        <h1 className="text-2xl font-bold text-center text-gray-800 mb-2">CrewMate</h1>
        <p className="text-sm text-center text-gray-500 mb-6">건설 인력 편성 플랫폼</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-gray-700 mb-1">
              아이디
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="worker1 / office1 / company1"
              required
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
              비밀번호
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="demo1234"
              required
            />
          </div>

          {error && (
            <p className="text-sm text-red-600" role="alert">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? '로그인 중...' : '로그인'}
          </button>
        </form>

        <p className="text-sm text-center text-gray-500 mt-4">
          계정이 없으신가요?{' '}
          <Link to="/signup" className="text-blue-600 hover:underline">회원가입</Link>
        </p>

        <div className="mt-6 p-3 bg-gray-50 rounded-lg">
          <p className="text-xs text-gray-500 font-medium mb-2">데모 계정</p>
          <div className="text-xs text-gray-600 space-y-1">
            <p><span className="font-mono">worker1 / worker2 / worker3</span> — 근로자</p>
            <p><span className="font-mono">office1</span> — 인력사무소</p>
            <p><span className="font-mono">company1</span> — 건설사</p>
            <p className="text-gray-400 mt-1">비밀번호: demo1234</p>
          </div>
        </div>
      </div>
    </div>
  );
}
