import { useState, useEffect } from 'react';
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

const ALL_TRADES: Trade[] = ['FORMWORK', 'REBAR', 'MASONRY', 'MATERIAL_CARRY', 'GENERAL'];

interface SelectedMember {
  worker_id: string;
  assigned_trade: Trade;
  offered_wage: number;
}

export default function ComposePage() {
  const { requestId } = useParams<{ requestId: string }>();
  const navigate = useNavigate();

  const [request, setRequest] = useState<WorkRequest | null>(null);
  const [candidates, setCandidates] = useState<Worker[]>([]);
  const [selected, setSelected] = useState<SelectedMember[]>([]);
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
      if (workersRes.success) setCandidates(workersRes.data.filter((w) => w.state === 'READY'));
      setLoading(false);
    })();
  }, [requestId]);

  // worker가 특정 직종에 배치 가능한지 (excluded가 아닌지)
  const canAssignTrade = (worker: Worker, trade: Trade) => {
    return !worker.excluded_trades.includes(trade);
  };

  // worker가 아무 직종에도 배치 불가한지 (모든 요청 직종이 excluded)
  const isFullyExcluded = (worker: Worker) => {
    if (!request) return false;
    return request.required_workers.every((rw) => worker.excluded_trades.includes(rw.trade));
  };

  const isSelected = (workerId: string) => selected.some((s) => s.worker_id === workerId);

  const getDefaultTrade = (worker: Worker): Trade => {
    if (!request) return ALL_TRADES[0];
    // 희망 직종 중 요청에 있는 것 우선
    for (const pt of worker.preferred_trades) {
      if (request.required_workers.some((rw) => rw.trade === pt)) return pt;
    }
    // 그 외 배치 가능한 것
    for (const rw of request.required_workers) {
      if (canAssignTrade(worker, rw.trade)) return rw.trade;
    }
    return ALL_TRADES[0];
  };

  const toggleWorker = (worker: Worker) => {
    if (isSelected(worker.worker_id)) {
      setSelected(selected.filter((s) => s.worker_id !== worker.worker_id));
    } else {
      setSelected([...selected, {
        worker_id: worker.worker_id,
        assigned_trade: getDefaultTrade(worker),
        offered_wage: worker.desired_daily_wage,
      }]);
    }
  };

  const updateMember = (workerId: string, field: 'assigned_trade' | 'offered_wage', value: string | number) => {
    setSelected(selected.map((s) =>
      s.worker_id === workerId
        ? { ...s, [field]: field === 'offered_wage' ? Number(value) : value }
        : s
    ));
  };

  // 직종별 충족 현황
  const getTradeStatus = (): { trade: Trade; required: number; have: number }[] => {
    if (!request) return [];
    return request.required_workers.map((rw: RequiredWorker) => {
      const have = selected.filter((s) => s.assigned_trade === rw.trade).length;
      return { trade: rw.trade, required: rw.count, have };
    });
  };

  const tradeStatus = getTradeStatus();
  const allFulfilled = tradeStatus.every((t) => t.have >= t.required);
  const totalCost = selected.reduce((s, m) => s + m.offered_wage, 0);
  const overBudget = request ? totalCost > request.budget && request.budget > 0 : false;

  const handleApprove = async () => {
    if (!requestId) return;
    setApproving(true);
    setError('');
    setConflictError('');

    const crewRes = await api.post<Crew>('/office/crews/manual', {
      request_id: requestId,
      members: selected,
    });

    if (!crewRes.success) {
      setApproving(false);
      setError(crewRes.error.message);
      return;
    }

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

  if (loading) return <p className="text-center text-gray-400 py-10">불러오는 중...</p>;
  if (!request) return <p className="text-center text-gray-500 py-10">요청을 찾을 수 없습니다.</p>;

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">수동 편성 — {request.site_name}</h2>
        <button onClick={() => navigate(`/office/requests/${requestId}`)}
          className="text-sm text-gray-500 hover:text-gray-800">← 돌아가기</button>
      </div>

      {/* 직종별 충족 현황 */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h3 className="text-sm font-medium text-gray-500 mb-2">
          직종별 충족 현황 {allFulfilled && <span className="ml-2 text-green-600">✓ 모두 충족</span>}
        </h3>
        <div className="flex flex-wrap gap-3">
          {tradeStatus.map((t) => (
            <div key={t.trade} className={`px-3 py-2 rounded-lg text-sm ${t.have >= t.required ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
              <span className="font-medium">{TRADE_LABEL[t.trade]}</span>
              <span className="ml-2">{t.have}/{t.required}명</span>
            </div>
          ))}
        </div>
        <div className="mt-2 text-sm text-gray-500">
          선택: {selected.length}명 / 예상 총 비용: {totalCost.toLocaleString()}원
          {request.budget > 0 && <span className="ml-2 text-gray-400">/ 총예산: {request.budget.toLocaleString()}원</span>}
          {overBudget && <span className="text-red-600 ml-2">⚠ 총예산 초과 — 승인 불가</span>}
        </div>
      </div>

      {/* 에러 */}
      {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm p-3 rounded-lg">{error}</div>}
      {conflictError && (
        <div className="bg-yellow-50 border border-yellow-200 p-4 rounded-lg">
          <p className="text-yellow-800 font-medium text-sm">⚠ 배정 충돌</p>
          <p className="text-yellow-700 text-sm mt-1">{conflictError}</p>
        </div>
      )}

      {/* 선택된 멤버 — 직종/금액 조절 */}
      {selected.length > 0 && (
        <div className="bg-purple-50 rounded-lg border border-purple-200 p-4">
          <h3 className="text-sm font-medium text-purple-700 mb-3">선택된 인원 ({selected.length}명)</h3>
          <div className="space-y-2">
            {selected.map((s) => {
              const w = candidates.find((c) => c.worker_id === s.worker_id)!;
              return (
                <div key={s.worker_id} className="flex items-center gap-3 bg-white rounded p-2">
                  <span className="font-medium text-sm text-gray-800 w-16">{w.name}</span>
                  <select value={s.assigned_trade}
                    onChange={(e) => updateMember(s.worker_id, 'assigned_trade', e.target.value)}
                    className="border border-gray-300 rounded px-2 py-1 text-sm">
                    {ALL_TRADES.filter((t) => canAssignTrade(w, t)).map((t) => (
                      <option key={t} value={t}>{TRADE_LABEL[t]}{w.preferred_trades.includes(t) ? ' ★' : ''}</option>
                    ))}
                  </select>
                  <input type="text" inputMode="numeric" value={s.offered_wage || ''}
                    onChange={(e) => { const v = e.target.value.replace(/[^0-9]/g, ''); updateMember(s.worker_id, 'offered_wage', v ? Number(v) : 0); }}
                    className="w-28 border border-gray-300 rounded px-2 py-1 text-sm" />
                  <span className="text-xs text-gray-400">원</span>
                  <button onClick={() => setSelected(selected.filter((x) => x.worker_id !== s.worker_id))}
                    className="text-gray-400 hover:text-red-500 ml-auto">×</button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 후보 테이블 */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="w-10 px-4 py-3"></th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium">이름</th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium">희망 직종</th>
              <th className="text-center px-4 py-3 text-gray-500 font-medium">숙련</th>
              <th className="text-right px-4 py-3 text-gray-500 font-medium">희망 일당</th>
              <th className="text-left px-4 py-3 text-gray-500 font-medium">지역</th>
              <th className="text-center px-4 py-3 text-gray-500 font-medium">배치 가능</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {candidates.map((w) => {
              const excluded = isFullyExcluded(w);
              const checked = isSelected(w.worker_id);
              return (
                <tr key={w.worker_id}
                  onClick={() => !excluded && toggleWorker(w)}
                  className={`transition-colors ${excluded ? 'opacity-40 cursor-not-allowed' : checked ? 'bg-purple-50 cursor-pointer' : 'hover:bg-gray-50 cursor-pointer'}`}>
                  <td className="px-4 py-3">
                    <input type="checkbox" checked={checked} disabled={excluded}
                      onChange={() => !excluded && toggleWorker(w)}
                      className="rounded border-gray-300" />
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-800">{w.name}</td>
                  <td className="px-4 py-3 text-gray-600">
                    <div className="flex flex-wrap gap-1">
                      {w.preferred_trades.map((t) => (
                        <span key={t} className="text-xs bg-green-50 text-green-700 px-1.5 py-0.5 rounded">{TRADE_LABEL[t]}</span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center">{'★'.repeat(w.skill_level)}</td>
                  <td className="px-4 py-3 text-right text-gray-600">{w.desired_daily_wage.toLocaleString()}원</td>
                  <td className="px-4 py-3 text-gray-600">{w.region}</td>
                  <td className="px-4 py-3 text-center">
                    {excluded ? (
                      <span className="text-xs text-red-500">불가</span>
                    ) : (
                      <span className="text-xs text-green-600">가능</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* 승인 버튼 */}
      <div className="flex justify-end">
        <button onClick={handleApprove}
          disabled={!allFulfilled || overBudget || approving || selected.length === 0}
          className="bg-purple-600 text-white px-6 py-2.5 rounded-md text-sm font-medium hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {approving ? '승인 처리 중...' : `편성 승인 (${selected.length}명)`}
        </button>
      </div>
    </div>
  );
}
