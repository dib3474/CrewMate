import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import type { WorkHistoryEntry } from '../../api/types';

const TRADE_LABEL: Record<string, string> = {
  FORMWORK: '형틀목공', REBAR: '철근공', MASONRY: '조적공',
  MATERIAL_CARRY: '자재운반', GENERAL: '보통인부',
};

export default function HistoryPage() {
  const navigate = useNavigate();

  const fetchHistory = useCallback(async () => {
    const res = await api.get<WorkHistoryEntry[]>('/worker/history');
    if (res.success) return res.data;
    return [];
  }, []);

  const { data: history, loading } = usePolling<WorkHistoryEntry[]>({
    fetchFn: fetchHistory,
    interval: 10000,
    enabled: true,
  });

  return (
    <div className="max-w-lg mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">작업 이력</h2>
        <button onClick={() => navigate('/worker')}
          className="text-sm text-gray-500 hover:text-gray-800">← 돌아가기</button>
      </div>

      {loading && !history && (
        <p className="text-center text-gray-400 py-6">불러오는 중...</p>
      )}

      {history && history.length === 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center">
          <p className="text-gray-500">아직 완료된 작업이 없습니다.</p>
        </div>
      )}

      {history && history.length > 0 && (
        <div className="space-y-3">
          {history.map((entry, idx) => (
            <div key={idx} className="bg-white rounded-lg border border-gray-200 p-4">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-medium text-gray-800">{entry.site_name}</h3>
                <span className="text-xs text-gray-400">{entry.work_date}</span>
              </div>
              <div className="flex items-center gap-4 text-sm text-gray-600">
                <span className="bg-green-50 text-green-700 px-2 py-0.5 rounded text-xs">
                  {TRADE_LABEL[entry.assigned_trade]}
                </span>
                <span>{entry.offered_wage.toLocaleString()}원</span>
              </div>
            </div>
          ))}

          <div className="bg-gray-50 rounded-lg p-4 text-center">
            <p className="text-sm text-gray-500">총 {history.length}건 완료</p>
            <p className="text-lg font-bold text-gray-800 mt-1">
              {history.reduce((s, e) => s + e.offered_wage, 0).toLocaleString()}원 수입
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
