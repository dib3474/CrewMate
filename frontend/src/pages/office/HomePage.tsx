import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import type { WorkRequest, WorkRequestStatus } from '../../api/types';

const STATUS_CONFIG: Record<WorkRequestStatus, { label: string; color: string }> = {
  REQUESTED: { label: '요청 접수', color: 'bg-yellow-100 text-yellow-700' },
  COMPOSING: { label: '편성 중', color: 'bg-purple-100 text-purple-700' },
  PROPOSED: { label: '추천 완료', color: 'bg-indigo-100 text-indigo-700' },
  APPROVED: { label: '수락 대기', color: 'bg-blue-100 text-blue-700' },
  DISPATCHED: { label: '배차 완료', color: 'bg-teal-100 text-teal-700' },
  RUNNING: { label: '작업 중', color: 'bg-orange-100 text-orange-700' },
  COMPLETED: { label: '완료', color: 'bg-green-100 text-green-700' },
  CANCELLED: { label: '취소', color: 'bg-gray-100 text-gray-500' },
};

const TRADE_LABEL: Record<string, string> = {
  FORMWORK: '형틀목공',
  REBAR: '철근공',
  MASONRY: '조적공',
  MATERIAL_CARRY: '자재운반',
  GENERAL: '보통인부',
};

export default function OfficeHomePage() {
  const navigate = useNavigate();

  const fetchRequests = useCallback(async () => {
    const res = await api.get<WorkRequest[]>('/office/requests');
    if (res.success) return res.data;
    return [];
  }, []);

  const { data: requests, loading } = usePolling<WorkRequest[]>({
    fetchFn: fetchRequests,
    interval: 5000,
  });

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">인력 요청 관리</h2>
        <button
          onClick={() => navigate('/office/workers')}
          className="text-sm text-purple-600 hover:text-purple-800 transition-colors"
        >
          근로자 목록 보기 →
        </button>
      </div>

      {loading && !requests && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center">
          <p className="text-gray-400">불러오는 중...</p>
        </div>
      )}

      {requests && requests.length === 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-10 text-center">
          <p className="text-gray-500">접수된 인력 요청이 없습니다.</p>
          <p className="text-sm text-gray-400 mt-2">건설사가 인력 요청을 생성하면 여기에 나타납니다.</p>
        </div>
      )}

      {requests && requests.length > 0 && (
        <div className="space-y-3">
          {requests.map((req) => {
            const statusInfo = STATUS_CONFIG[req.status];
            const totalWorkers = req.required_workers.reduce((s, w) => s + w.count, 0);
            const canCompose = req.status === 'REQUESTED';

            return (
              <div
                key={req.request_id}
                onClick={() => navigate(`/office/requests/${req.request_id}`)}
                className="bg-white rounded-lg border border-gray-200 p-5 hover:border-purple-300 hover:shadow-sm cursor-pointer transition-all"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-medium text-gray-800">{req.site_name}</h3>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusInfo.color}`}>
                        {statusInfo.label}
                      </span>
                      {canCompose && (
                        <span className="text-xs bg-purple-50 text-purple-600 px-2 py-0.5 rounded-full">
                          편성 가능
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-500">{req.location_text}</p>
                  </div>
                  <div className="text-right text-sm">
                    <p className="text-gray-800 font-medium">{req.work_date}</p>
                    <p className="text-gray-400">{req.start_time}</p>
                  </div>
                </div>

                <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
                  <span>필요 인원: {totalWorkers}명</span>
                  <span>
                    {req.required_workers.map((w) => `${TRADE_LABEL[w.trade] || w.trade} ${w.count}명`).join(', ')}
                  </span>
                  <span className="ml-auto">예산: {req.budget.toLocaleString()}원</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
