import { useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import type { WorkRequest, WorkRequestStatus, Crew, CrewMember, AcceptanceStatus } from '../../api/types';

const STATUS_STEPS: WorkRequestStatus[] = ['REQUESTED', 'APPROVED', 'DISPATCHED', 'RUNNING', 'COMPLETED'];

const STATUS_LABEL: Record<string, string> = {
  REQUESTED: '요청됨', COMPOSING: '편성 중', PROPOSED: '추천 완료',
  APPROVED: '수락 대기', DISPATCHED: '배차 완료', RUNNING: '작업 중',
  COMPLETED: '완료', CANCELLED: '취소',
};

const TRADE_LABEL: Record<string, string> = {
  FORMWORK: '형틀목공', REBAR: '철근공', MASONRY: '조적공',
  MATERIAL_CARRY: '자재운반', GENERAL: '보통인부',
};

const PRIORITY_LABEL: Record<string, string> = { HIGH: '높음', MEDIUM: '보통', LOW: '낮음' };

const ACCEPTANCE_CONFIG: Record<AcceptanceStatus, { label: string; color: string }> = {
  PENDING: { label: '응답 대기', color: 'bg-yellow-100 text-yellow-700' },
  ACCEPTED: { label: '수락', color: 'bg-green-100 text-green-700' },
  DECLINED: { label: '거절', color: 'bg-red-100 text-red-700' },
};

interface RequestDetail extends WorkRequest { crew: Crew | null; }

export default function RequestDetailPage() {
  const { requestId } = useParams<{ requestId: string }>();
  const navigate = useNavigate();
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    if (!requestId) return null;
    const res = await api.get<RequestDetail>(`/company/requests/${requestId}`);
    if (res.success) return res.data;
    return null;
  }, [requestId]);

  const { data: detail, refetch } = usePolling<RequestDetail | null>({ fetchFn: fetchDetail, interval: 3000 });

  const handleCheckin = async (workerId: string) => {
    setActionLoading(workerId + '_in');
    const crewId = detail?.crew?.crew_id;
    await api.post(`/company/crews/${crewId}/checkin/${workerId}`, { worker_id: workerId });
    setActionLoading(null);
    refetch();
  };

  const handleCheckout = async (workerId: string) => {
    setActionLoading(workerId + '_out');
    await api.post(`/company/crews/${detail?.crew?.crew_id}/checkout/${workerId}`, { worker_id: workerId });
    setActionLoading(null);
    refetch();
  };

  if (!detail) return <p className="text-center text-gray-400 py-10">불러오는 중...</p>;

  const currentStepIdx = STATUS_STEPS.indexOf(detail.status);
  const isDispatched = detail.status === 'DISPATCHED' || detail.status === 'RUNNING';

  return (
    <div className="max-w-2xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">{detail.site_name}</h2>
        <button onClick={() => navigate('/company')} className="text-sm text-gray-500 hover:text-gray-800">← 목록으로</button>
      </div>

      {/* 상태 진행 표시 */}
      {detail.status !== 'CANCELLED' && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-medium text-gray-500 mb-3">진행 상태</h3>
          <div className="flex items-center gap-1">
            {STATUS_STEPS.map((step, idx) => {
              const isActive = idx <= currentStepIdx;
              const isCurrent = idx === currentStepIdx;
              return (
                <div key={step} className="flex-1 flex flex-col items-center">
                  <div className={`w-full h-2 rounded-full ${isActive ? 'bg-orange-500' : 'bg-gray-200'} ${isCurrent ? 'animate-pulse' : ''}`} />
                  <span className={`text-[10px] mt-1 ${isActive ? 'text-orange-600 font-medium' : 'text-gray-400'}`}>{STATUS_LABEL[step]}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 배차 완료 배너 */}
      {detail.status === 'DISPATCHED' && (
        <div className="bg-green-50 border border-green-200 p-4 rounded-lg text-center">
          <p className="text-green-700 font-medium">✓ 전원 수락 완료 — 배차 확정</p>
          <p className="text-green-600 text-sm mt-1">작업일에 출근 확인 버튼으로 출석을 처리해주세요.</p>
        </div>
      )}

      {/* 요청 정보 */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-medium text-gray-500 mb-3">요청 정보</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div><span className="text-gray-500">작업일</span><p className="font-medium text-gray-800">{detail.work_date}</p></div>
          <div><span className="text-gray-500">시작 시간</span><p className="font-medium text-gray-800">{detail.start_time}</p></div>
          <div className="col-span-2"><span className="text-gray-500">위치</span><p className="font-medium text-gray-800">{detail.location_text}</p></div>
          <div><span className="text-gray-500">예산</span><p className="font-medium text-gray-800">{detail.budget.toLocaleString()}원</p></div>
          <div><span className="text-gray-500">우선순위</span><p className="font-medium text-gray-800 text-xs">비용 {PRIORITY_LABEL[detail.priority.cost]} / 숙련 {PRIORITY_LABEL[detail.priority.skill]} / 팀워크 {PRIORITY_LABEL[detail.priority.teamwork]}</p></div>
        </div>
      </div>

      {/* 작업조 + 출퇴근 관리 */}
      {detail.crew && detail.crew.members.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-medium text-gray-500 mb-3">
            작업조 {isDispatched && <span className="text-xs text-orange-600 ml-2">출퇴근 관리</span>}
          </h3>
          <div className="space-y-2">
            {detail.crew.members.map((member: CrewMember) => {
              const accInfo = ACCEPTANCE_CONFIG[member.acceptance];
              // 실제 worker 상태를 알려면 별도 API 필요하지만, mock에서는 acceptance 기준으로 표시
              const isReserved = member.acceptance === 'ACCEPTED' && (detail.status === 'DISPATCHED');
              const isRunning = detail.status === 'RUNNING';

              return (
                <div key={member.worker_id} className="flex items-center justify-between text-sm py-2.5 px-3 bg-orange-50 rounded">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-gray-800">{member.name}</span>
                    <span className="text-xs text-gray-500">{TRADE_LABEL[member.assigned_trade]}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${accInfo.color}`}>{accInfo.label}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">{member.offered_wage.toLocaleString()}원</span>
                    {/* 출근 버튼: 배차완료(DISPATCHED) 상태에서 */}
                    {isReserved && (
                      <button onClick={() => handleCheckin(member.worker_id)}
                        disabled={actionLoading === member.worker_id + '_in'}
                        className="px-2 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700 disabled:opacity-50">
                        {actionLoading === member.worker_id + '_in' ? '...' : '출근'}
                      </button>
                    )}
                    {/* 퇴근 버튼: RUNNING 상태에서 */}
                    {isRunning && (
                      <button onClick={() => handleCheckout(member.worker_id)}
                        disabled={actionLoading === member.worker_id + '_out'}
                        className="px-2 py-1 bg-gray-600 text-white text-xs rounded hover:bg-gray-700 disabled:opacity-50">
                        {actionLoading === member.worker_id + '_out' ? '...' : '퇴근'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            <div className="flex justify-between text-sm pt-2 border-t border-gray-200 font-medium">
              <span>총 비용</span>
              <span>{detail.crew.members.reduce((s, m) => s + m.offered_wage, 0).toLocaleString()}원</span>
            </div>
          </div>
        </div>
      )}

      {/* 필요 인원 */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-medium text-gray-500 mb-3">필요 인원</h3>
        <div className="space-y-2">
          {detail.required_workers.map((rw, idx) => (
            <div key={idx} className="flex items-center justify-between text-sm py-1.5 px-3 bg-gray-50 rounded">
              <span className="text-gray-700">{TRADE_LABEL[rw.trade] || rw.trade}</span>
              <span className="font-medium text-gray-800">{rw.count}명</span>
            </div>
          ))}
        </div>
      </div>

      {detail.notes && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-medium text-gray-500 mb-2">비고</h3>
          <p className="text-sm text-gray-700">{detail.notes}</p>
        </div>
      )}
    </div>
  );
}
