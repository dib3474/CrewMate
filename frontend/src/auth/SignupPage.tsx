import { useState, type FormEvent } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from './AuthContext';
import type { UserRole } from '../api/types';

const ROLE_HOME: Record<string, string> = {
  WORKER: '/worker',
  OFFICE: '/office',
  COMPANY: '/company',
};

const ROLE_OPTIONS: {
  value: UserRole; label: string; desc: string;
  selectedBorder: string; selectedBg: string; dot: string;
}[] = [
  { value: 'WORKER', label: '근로자', desc: '일자리를 찾고 배정받아요', selectedBorder: 'border-green-500', selectedBg: 'bg-green-50', dot: 'bg-green-500' },
  { value: 'OFFICE', label: '인력사무소', desc: '근로자를 관리하고 작업조를 편성해요', selectedBorder: 'border-purple-500', selectedBg: 'bg-purple-50', dot: 'bg-purple-500' },
  { value: 'COMPANY', label: '건설사', desc: '현장 인력을 요청해요', selectedBorder: 'border-orange-500', selectedBg: 'bg-orange-50', dot: 'bg-orange-500' },
];

const NAME_LABEL: Record<UserRole, string> = {
  WORKER: '이름',
  OFFICE: '사무소명',
  COMPANY: '회사명',
};

const REGION_LABEL: Record<UserRole, string> = {
  WORKER: '거주 지역',
  OFFICE: '활동 지역',
  COMPANY: '소재 지역',
};

const REGION_HINT: Record<UserRole, string> = {
  WORKER: '일하고 싶은 지역을 입력하세요.',
  OFFICE: '근로자·건설사가 사무소를 고를 때 표시됩니다.',
  COMPANY: '현장이 주로 위치한 지역을 입력하세요.',
};

export default function SignupPage() {
  const { signup } = useAuth();
  const navigate = useNavigate();

  const [role, setRole] = useState<UserRole>('WORKER');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [name, setName] = useState('');
  const [region, setRegion] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.');
      return;
    }
    if (password.length < 4) {
      setError('비밀번호는 4자 이상이어야 합니다.');
      return;
    }
    if (!region.trim()) {
      setError('지역을 입력해주세요.');
      return;
    }

    setLoading(true);
    const result = await signup({ username, password, role, name, region });
    setLoading(false);

    if (result.success && result.role) {
      navigate(ROLE_HOME[result.role], { replace: true });
    } else {
      setError(result.error || '회원가입에 실패했습니다.');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-10">
      <div className="w-full max-w-md p-8 bg-white rounded-xl shadow-md">
        <h1 className="text-2xl font-bold text-center text-gray-800 mb-2">회원가입</h1>
        <p className="text-sm text-center text-gray-500 mb-6">CrewMate에 오신 것을 환영합니다</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 역할 선택 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">역할 선택</label>
            <div className="space-y-2">
              {ROLE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setRole(opt.value)}
                  className={`w-full text-left px-4 py-3 rounded-lg border-2 transition-colors ${
                    role === opt.value
                      ? `${opt.selectedBorder} ${opt.selectedBg}`
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`w-3 h-3 rounded-full ${role === opt.value ? opt.dot : 'bg-gray-300'}`} />
                    <span className="font-medium text-gray-800">{opt.label}</span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1 ml-5">{opt.desc}</p>
                </button>
              ))}
            </div>
          </div>

          {/* 이름/상호명 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{NAME_LABEL[role]}</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder={role === 'WORKER' ? '홍길동' : role === 'OFFICE' ? '부산인력사무소' : '해운대건설'}
              required
            />
          </div>

          {/* 지역 (모든 역할) */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{REGION_LABEL[role]}</label>
            <input
              type="text"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="예: 부산 해운대구"
              required
            />
            <p className="text-xs text-gray-400 mt-1">{REGION_HINT[role]}</p>
          </div>

          {/* 아이디 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">아이디</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="사용할 아이디"
              required
            />
          </div>

          {/* 비밀번호 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">비밀번호</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="4자 이상"
              required
            />
          </div>

          {/* 비밀번호 확인 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">비밀번호 확인</label>
            <input
              type="password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="비밀번호 재입력"
              required
            />
          </div>

          {error && <p className="text-sm text-red-600" role="alert">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-4 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? '가입 중...' : '회원가입'}
          </button>
        </form>

        <p className="text-sm text-center text-gray-500 mt-4">
          이미 계정이 있으신가요?{' '}
          <Link to="/login" className="text-blue-600 hover:underline">로그인</Link>
        </p>
      </div>
    </div>
  );
}
