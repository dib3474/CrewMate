import { useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import type { WorkRequest, Crew, CrewMember, AcceptanceStatus, WorkerState } from '../../api/types';

const STATUS_LABEL: Record<string, string> = {
  REQUESTED: '요청 접수', COMPOSING: '편성 중', PROPOSED: '추천 완료',
  APPROVED: '수락 대기', DISPATCHED: '배차 완료', RUNNING: '작업 중',
  COMPLETED: '완료', CANCELLED: '취소', NOTIFIED: '수락 대기', DRAFT: '임시', REJECTED: '거절됨',
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

const WORKER_STATE_BADGE: Record<WorkerState, { label: string; color: string }> = {
  INACTIVE: { label: '퇴근 완료', color: 'bg-gray-100 text-gray-600' },
  READY: { label: '대기', color: 'bg-gray-100 text-gray-600' },
  NOTIFIED: { label: '제안 중', color: 'bg-purple-100 text-purple-600' },
  RESERVED: { label: '배차 완료', color: 'bg-blue-100 text-blue-700' },
  RUNNING: { label: '작업 중', color: 'bg-orange-100 text-orange-700' },
};

const REJECT_REASONS = ['인원 부족', '해당 직종 근로자 부재', '일정 충돌', '기타'];
const OFFER_TIMEOUT_MS = 30 * 60 * 1000; // 30분

interface CrewMemberWithState extends CrewMember { worker_state: WorkerState; }
interface RequestDetail extends WorkRequest { crew: (Crew & { members: CrewMemberWithState[] }) | null; }

export default function OfficeRequestDetailPage() {
  const { requestId } = useParams<{ requestId: string }>();
  const navigate = useNavigate();
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState(REJECT_REASONS[0]);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [cancellingWorker, setCancellingWorker] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    if (!requestId) return null;
    const res = await api.get<RequestDetail>(`/office/requests/${requestId}`);
    if (res.success) return res.data;
    return null;
  }, [requestId]);

  const { data: detail, refetch } = usePolling<RequestDetail | null>({ fetchFn: fetchDetail, interval: 3000 });

  const handleReject = async () => {
    setRejecting(true);
    await api.post(`/office/requests/${requestId}/reject`, { reason: rejectReason });
    setRejecting(false);
    setShowRejectModal(false);
    refetch();
  };

  const handleCancelOffer = async (workerId: string, workerName: string) => {
    if (!confirm(`${workerName}님의 제안을 취소하시겠습니까?\n취소 시 해당 근로자는 비활성(INACTIVE) 상태가 됩니다.`)) return;
    setCancellingWorker(workerId);
    const crewId = detail?.crew?.crew_id;
    await api.post(`/office/crews/${crewId}/cancel-offer/${workerId}`, { worker_id: workerId });
    setCancellingWorker(null);
    refetch();
  };

  if (!detail) return <p className="text-center text-gray-400 py-10">불러오는 중...</p>;

  const canCompose = detail.status === 'REQUESTED';
  const hasDeclined = detail.crew?.members.some((m) => m.acceptance === 'DECLINED');

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">{detail.site_name}</h2>
        <button onClick={() => navigate('/office')} className="text-sm text-gray-500 hover:text-gray-800">← 목록으로</button>
      </div>

      {/* 상태 + 액션 */}
      <div className="bg-white rounded-lg border border-gray-200 p-5 flex items-center justify-between">
        <div>
          <span className="text-sm text-gray-500">상태: </span>
          <span className="font-medium text-gray-800">{STATUS_LABEL[detail.status] || detail.status}</span>
        </div>
        <div className="flex gap-2">
          {canCompose && (
            <>
              <button onClick={() => navigate(`/office/compose/${requestId}`)}
                className="bg-purple-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-purple-700 transition-colors">
                수동 편성하기
              </button>
              <button onClick={() => setShowRejectModal(true)}
                className="bg-white border border-red-300 text-red-600 px-4 py-2 rounded-md text-sm font-medium hover:bg-red-50 transition-colors">
                거절
              </button>
            </>
          )}
          {hasDeclined && (
            <button onClick={() => navigate(`/office/compose/${requestId}`)}
              className="bg-red-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-red-700 transition-colors">
              재편성하기
            </button>
          )}
        </div>
      </div>

      {/* 거절 모달 */}
      {showRejectModal && (
        <div className="bg-red-50 border border-red-200 p-5 rounded-lg">
          <h3 className="text-sm font-medium text-red-700 mb-3">요청 거절 사유 선택</h3>
          <div className="space-y-2 mb-4">
            {REJECT_REASONS.map((reason) => (
              <label key={reason} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                <input type="radio" name="rejectReason" value={reason}
                  checked={rejectReason === reason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  className="text-red-600" />
                {reason}
              </label>
            ))}
          </div>
          <div className="flex gap-2">
            <button onClick={handleReject} disabled={rejecting}
              className="bg-red-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-red-700 disabled:opacity-50">
              {rejecting ? '처리 중...' : '거절 확정'}
            </button>
            <button onClick={() => setShowRejectModal(false)}
              className="px-4 py-2 border border-gray-300 text-gray-700 rounded-md text-sm hover:bg-gray-50">
              취소
            </button>
          </div>
        </div>
      )}

      {/* 거절/완료 배너 */}
      {detail.status === 'REJECTED' && (
        <div className="bg-red-50 border border-red-200 p-4 rounded-lg text-center">
          <p className="text-red-700 font-medium">이 요청을 거절했습니다</p>
          {detail.rejection_reason && <p className="text-red-600 text-sm mt-1">사유: {detail.rejection_reason}</p>}
        </div>
      )}
      {hasDeclined && (
        <div className="bg-red-50 border border-red-200 p-4 rounded-lg">
          <p className="text-red-700 font-medium text-sm">⚠ 일부 근로자가 배정을 거절했습니다</p>
          <p className="text-red-600 text-sm mt-1">거절한 인원을 교체하여 재편성해주세요.</p>
        </div>
      )}
      {detail.status === 'COMPLETED' && (
        <div className="bg-gray-50 border border-gray-200 p-4 rounded-lg text-center">
          <p className="text-gray-700 font-medium">✓ 작업 완료</p>
        </div>
      )}

      {/* 요청 정보 */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-medium text-gray-500 mb-3">요청 정보</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div><span className="text-gray-500">작업일</span><p className="font-medium text-gray-800">{detail.work_date}</p></div>
          <div><span className="text-gray-500">시작 시간</span><p className="font-medium text-gray-800">{detail.start_time}</p></div>
          <div className="col-span-2"><span className="text-gray-500">위치</span><p className="font-medium text-gray-800">{detail.location_text}</p></div>
          <div><span className="text-gray-500">총예산</span><p className="font-medium text-gray-800">{detail.budget.toLocaleString()}원</p></div>
          <div><span className="text-gray-500">우선순위</span><p className="font-medium text-gray-800 text-xs">비용 {PRIORITY_LABEL[detail.priority.cost]} / 숙련 {PRIORITY_LABEL[detail.priority.skill]} / 팀워크 {PRIORITY_LABEL[detail.priority.teamwork]}</p></div>
        </div>
      </div>

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

      {/* 작업조 + 개별 상태 + 제안취소 */}
      {detail.crew && detail.crew.members.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-medium text-gray-500 mb-3">
            작업조 <span className="text-xs text-gray-400">({STATUS_LABEL[detail.crew.status] || detail.crew.status})</span>
          </h3>
          <div className="space-y-2">
            {detail.crew.members.map((member: CrewMemberWithState) => {
              const accInfo = ACCEPTANCE_CONFIG[member.acceptance];
              const stateInfo = WORKER_STATE_BADGE[member.worker_state];
              const isPending = member.acceptance === 'PENDING';
              const isTimedOut = isPending && member.notified_at && (Date.now() - new Date(member.notified_at).getTime() > OFFER_TIMEOUT_MS);

              return (
                <div key={member.worker_id} className={`flex items-center justify-between text-sm py-2.5 px-3 rounded ${isPending ? 'bg-yellow-50' : 'bg-purple-50'}`}>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-800">{member.name}</span>
                    <span className="text-xs text-gray-500">{TRADE_LABEL[member.assigned_trade]}</span>
                    {member.acceptance !== 'ACCEPTED' && (
                      <span className={`text-xs px-1.5 py-0.5 rounded-full ${accInfo.color}`}>{accInfo.label}</span>
                    )}
                    {member.acceptance === 'ACCEPTED' && (
                      <span className={`text-xs px-1.5 py-0.5 rounded-full ${stateInfo.color}`}>{stateInfo.label}</span>
                    )}
                    {isTimedOut && <span className="text-xs text-red-500 font-medium">⏰ 타임아웃</span>}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-gray-400">{member.offered_wage.toLocaleString()}원</span>
                    {isPending && (
                      <button onClick={() => handleCancelOffer(member.worker_id, member.name)}
                        disabled={cancellingWorker === member.worker_id}
                        className="px-2 py-1 bg-white border border-red-300 text-red-600 text-xs rounded hover:bg-red-50 disabled:opacity-50">
                        {cancellingWorker === member.worker_id ? '...' : '제안 취소'}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
            <div className="flex justify-between text-sm pt-2 border-t border-gray-200 font-medium">
              <span>예상 총 비용</span>
              <span>{detail.crew.members.reduce((s, m) => s + m.offered_wage, 0).toLocaleString()}원</span>
            </div>
          </div>
        </div>
      )}

      {detail.notes && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-medium text-gray-500 mb-2">비고</h3>
          <p className="text-sm text-gray-700">{detail.notes}</p>
        </div>
      )}
    </div>
  );
}
