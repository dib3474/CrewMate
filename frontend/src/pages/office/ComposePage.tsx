import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import type { Worker, WorkRequest, Crew, Trade, RequiredWorker } from '../../api/types';

const TRADE_LABEL: Record<string, string> = {
  FORMWORK: '형틀목공',
  REBAR: '철근공',
  MASONRY: '조적공',
  MATERIAL_CARRY: '자재운반',
  GENERAL: '보통인부',
};

export default function ComposePage() {
  const { requestId } = useParams<{ requestId: string }>();
  const navigate = useNavigate();

  const [request, setRequest] = useState<WorkRequest | null>(null);
  const [candidates, setCandidates] = useState<Worker[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState('');
  const [conflictError, setConflictError] = useState('');

  useEffect(() => {
    (async () => {
      const [reqRes, workersRes] = await Promise.all([
        api.get<WorkRequest & { crew: Crew | null }>(`/office/requests/${requestId}`),
        api.get<Worker[]>('/office/workers'),
      ]);
      if (reqRes.success) setRequest(reqRes.data);
      if (workersRes.success) {
        setCandidates(workersRes.data.filter((w) => w.state === 'READY'));
      }
      setLoading(false);
    })();
  }, [requestId]);

  const toggleWorker = (workerId: string) => {
    const next = new Set(selected);
    if (next.has(workerId)) next.delete(workerId);
    else next.add(workerId);
    setSelected(next);
  };

  // 직종별 충족 현황 계산
  const getTradeStatus = useCallback((): { trade: Trade; required: number; have: number }[] => {
    if (!request) return [];
    return request.required_workers.map((rw: RequiredWorker) => {
      const have = candidates.filter(
        (w) => selected.has(w.worker_id) && w.trade === rw.trade
      ).length;
      return { trade: rw.trade, required: rw.count, have };
    });
  }, [request, candidates, selected]);

  const tradeStatus = getTradeStatus();
  const allFulfilled = tradeStatus.every((t) => t.have >= t.required);
  const totalCost = candidates
    .filter((w) => selected.has(w.worker_id))
    .reduce((s, w) => s + w.desired_daily_wage, 0);

  const handleApprove = async () => {
    if (!requestId) return;
    setApproving(true);
    setError('');
    setConflictError('');

    // 1. 크루 생성
    const crewRes = await api.post<Crew>('/office/crews/manual', {
      request_id: requestId,
      member_ids: Array.from(selected),
    });

    if (!crewRes.success) {
      setApproving(false);
      setError(crewRes.error.message);
      return;
    }

    // 2. 승인
    const crew = crewRes.data;
    const approveRes = await api.post<Crew>(`/office/crews/${crew.crew_id}/approve`);

    setApproving(false);

    if (approveRes.success) {
      navigate(`/office/requests/${requestId}`);
    } else if (approveRes.error.code === 'STATE_CONFLICT') {
      setConflictError(approveRes.error.message);
    } else {
      setError(approveRes.error.message);
    }
  };

  if (loading) {
    return <p className="text-center text-gray-400 py-10">불러오는 중...</p>;
  }

  if (!request) {
    return <p className="text-center text-gray-500 py-10">요청을 찾을 수 없습니다.</p>;
  }

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">
          수동 편성 — {request.site_name}
        </h2>
        <button onClick={() => navigate(`/office/requests/${requestId}`)}
          className="text-sm text-gray-500 hover:text-gray-800">
          ← 돌아가기
        </button>
      </div>

      {/* 직종별 충족 현황 */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h3 className="text-sm font-medium text-gray-500 mb-2">
          직종별 충족 현황
          {allFulfilled && <span className="ml-2 text-green-600">✓ 모두 충족</span>}
        </h3>
        <div className="flex flex-wrap gap-3">
          {tradeStatus.map((t) => (
            <div key={t.trade}
              className={`px-3 py-2 rounded-lg text-sm ${
                t.have >= t.required ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
              }`}>
              <span className="font-medium">{TRADE_LABEL[t.trade]}</span>
              <span className="ml-2">{t.have}/{t.required}명</span>
            </div>
          ))}
        </div>
        <div className="mt-2 text-sm text-gray-500">
          선택: {selected.size}명 / 예상 비용: {totalCost.toLocaleString()}원
          {request.budget > 0 && totalCost > request.budget && (
            <span className="text-red-600 ml-2">⚠ 예산 초과</span>
          )}
        </div>
      </div>

      {/* 에러 표시 */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm p-3 rounded-lg">
          {error}
        </div>
      )}
      {conflictError && (
        <div className="bg-yellow-50 border border-yellow-200 p-4 rounded-lg">
          <p className="text-yellow-800 font-medium text-sm">⚠ 배정 충돌</p>
          <p className="text-yellow-700 text-sm mt-1">{conflictError}</p>
          <p className="text-yellow-600 text-xs mt-2">
            다른 근로자를 선택하거나 AI 자동 편성을 시도해주세요.
          </p>
        </div>
      )}

      {/* 후보 테이블 */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="w-10 px-4 py-3"></th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium">이름</th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium">직종</th>
              <th className="text-center px-4 py-3 text-gray-500 font-medium">숙련</th>
              <th className="text-right px-4 py-3 text-gray-500 font-medium">일당</th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium">지역</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {candidates.map((w) => {
              const isSelected = selected.has(w.worker_id);
              return (
                <tr key={w.worker_id}
                  onClick={() => toggleWorker(w.worker_id)}
                  className={`cursor-pointer transition-colors ${
                    isSelected ? 'bg-purple-50' : 'hover:bg-gray-50'
                  }`}>
                  <td className="px-4 py-3">
                    <input type="checkbox" checked={isSelected}
                      onChange={() => toggleWorker(w.worker_id)}
                      className="rounded border-gray-300" />
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-800">{w.name}</td>
                  <td className="px-4 py-3 text-gray-600">
                    {TRADE_LABEL[w.trade] || w.trade}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {'★'.repeat(w.skill_level)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-600">
                    {w.desired_daily_wage.toLocaleString()}원
                  </td>
                  <td className="px-4 py-3 text-gray-600">{w.region}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* 승인 버튼 */}
      <div className="flex justify-end">
        <button
          onClick={handleApprove}
          disabled={!allFulfilled || approving || selected.size === 0}
          className="bg-purple-600 text-white px-6 py-2.5 rounded-md text-sm font-medium hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {approving ? '승인 처리 중...' : `편성 승인 (${selected.size}명)`}
        </button>
      </div>
    </div>
  );
}
