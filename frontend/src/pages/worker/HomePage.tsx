import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import type { Worker, WorkerState } from '../../api/types';

const STATE_CONFIG: Record<WorkerState, { label: string; color: string; bgColor: string }> = {
  INACTIVE: { label: '비활성', color: 'text-gray-700', bgColor: 'bg-gray-100' },
  READY: { label: '대기 중', color: 'text-green-700', bgColor: 'bg-green-100' },
  RESERVED: { label: '배정 확정', color: 'text-blue-700', bgColor: 'bg-blue-100' },
  RUNNING: { label: '작업 중', color: 'text-orange-700', bgColor: 'bg-orange-100' },
};

const TRADE_LABEL: Record<string, string> = {
  FORMWORK: '형틀목공',
  REBAR: '철근공',
  MASONRY: '조적공',
  MATERIAL_CARRY: '자재운반',
  GENERAL: '보통인부',
};

export default function WorkerHomePage() {
  const navigate = useNavigate();
  const [actionLoading, setActionLoading] = useState(false);

  const fetchWorker = useCallback(async () => {
    const res = await api.get<Worker>('/worker/me');
    if (res.success) return res.data;
    return null;
  }, []);

  const { data: worker, refetch } = usePolling<Worker | null>({
    fetchFn: fetchWorker,
    interval: 5000,
  });

  const handleReady = async () => {
    setActionLoading(true);
    const res = await api.post('/worker/state/ready');
    setActionLoading(false);
    if (res.success) {
      refetch();
    } else if (!res.success) {
      alert(res.error.message);
    }
  };

  const handleInactive = async () => {
    setActionLoading(true);
    const res = await api.post('/worker/state/inactive');
    setActionLoading(false);
    if (res.success) {
      refetch();
    } else if (!res.success) {
      alert(res.error.message);
    }
  };

  if (!worker) {
    return (
      <div className="max-w-lg mx-auto">
        <h2 className="text-xl font-semibold text-gray-800 mb-4">근로자 대시보드</h2>
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center">
          <p className="text-gray-500 mb-4">지원서를 먼저 작성해주세요.</p>
          <button
            onClick={() => navigate('/worker/application')}
            className="bg-green-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-green-700 transition-colors"
          >
            지원서 작성하기
          </button>
        </div>
      </div>
    );
  }

  const stateInfo = STATE_CONFIG[worker.state];

  return (
    <div className="max-w-lg mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">근로자 대시보드</h2>
        <button
          onClick={() => navigate('/worker/application')}
          className="text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          지원서 수정
        </button>
      </div>

      {/* 상태 카드 */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="text-center mb-6">
          <p className="text-sm text-gray-500 mb-2">현재 상태</p>
          <span className={`inline-block text-2xl font-bold px-4 py-2 rounded-lg ${stateInfo.bgColor} ${stateInfo.color}`}>
            {stateInfo.label}
          </span>
        </div>

        {/* 상태별 버튼 */}
        <div className="flex justify-center">
          {worker.state === 'INACTIVE' && (
            <button
              onClick={handleReady}
              disabled={actionLoading}
              className="bg-green-600 text-white px-6 py-2.5 rounded-md text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {actionLoading ? '처리 중...' : '대기 시작'}
            </button>
          )}
          {worker.state === 'READY' && (
            <button
              onClick={handleInactive}
              disabled={actionLoading}
              className="bg-gray-600 text-white px-6 py-2.5 rounded-md text-sm font-medium hover:bg-gray-700 disabled:opacity-50 transition-colors"
            >
              {actionLoading ? '처리 중...' : '대기 취소'}
            </button>
          )}
          {worker.state === 'RUNNING' && (
            <button
              onClick={() => navigate('/worker/assignments')}
              className="bg-orange-600 text-white px-6 py-2.5 rounded-md text-sm font-medium hover:bg-orange-700 transition-colors"
            >
              배정 정보 보기
            </button>
          )}
          {worker.state === 'RESERVED' && (
            <p className="text-sm text-blue-600">배정 확정 대기 중입니다. 곧 작업 정보가 안내됩니다.</p>
          )}
        </div>
      </div>

      {/* 프로필 요약 */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-3">내 정보</h3>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-gray-500">이름</span>
            <p className="font-medium text-gray-800">{worker.name}</p>
          </div>
          <div>
            <span className="text-gray-500">직종</span>
            <p className="font-medium text-gray-800">{TRADE_LABEL[worker.trade] || worker.trade}</p>
          </div>
          <div>
            <span className="text-gray-500">숙련도</span>
            <p className="font-medium text-gray-800">{'★'.repeat(worker.skill_level)}{'☆'.repeat(5 - worker.skill_level)}</p>
          </div>
          <div>
            <span className="text-gray-500">경력</span>
            <p className="font-medium text-gray-800">{worker.career_years}년</p>
          </div>
          <div>
            <span className="text-gray-500">지역</span>
            <p className="font-medium text-gray-800">{worker.region}</p>
          </div>
          <div>
            <span className="text-gray-500">희망 일당</span>
            <p className="font-medium text-gray-800">{worker.desired_daily_wage.toLocaleString()}원</p>
          </div>
        </div>
        {worker.certifications.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <span className="text-xs text-gray-500">자격증</span>
            <div className="flex flex-wrap gap-1 mt-1">
              {worker.certifications.map((cert) => (
                <span key={cert} className="text-xs bg-green-50 text-green-700 px-2 py-0.5 rounded-full">{cert}</span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 실적 */}
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-3">작업 실적</h3>
        <div className="flex gap-6">
          <div className="text-center">
            <p className="text-2xl font-bold text-gray-800">{worker.completed_count}</p>
            <p className="text-xs text-gray-500">완료 작업</p>
          </div>
        </div>
      </div>
    </div>
  );
}
