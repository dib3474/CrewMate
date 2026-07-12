import { useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import type { WorkRequest, Crew, CrewMember, WorkRequestStatus } from '../../api/types';

const STATUS_LABEL: Record<WorkRequestStatus, string> = {
  REQUESTED: '요청 접수',
  COMPOSING: '편성 중',
  PROPOSED: '추천 완료',
  APPROVED: '승인됨',
  RUNNING: '작업 중',
  COMPLETED: '완료',
  CANCELLED: '취소',
};

const TRADE_LABEL: Record<string, string> = {
  FORMWORK: '형틀목공',
  REBAR: '철근공',
  MASONRY: '조적공',
  MATERIAL_CARRY: '자재운반',
  GENERAL: '보통인부',
};

const PRIORITY_LABEL: Record<string, string> = {
  HIGH: '높음',
  MEDIUM: '보통',
  LOW: '낮음',
};

interface RequestDetail extends WorkRequest {
  crew: Crew | null;
}

export default function OfficeRequestDetailPage() {
  const { requestId } = useParams<{ requestId: string }>();
  const navigate = useNavigate();

  const fetchDetail = useCallback(async () => {
    if (!requestId) return null;
    const res = await api.get<RequestDetail>(`/office/requests/${requestId}`);
    if (res.success) return res.data;
    return null;
  }, [requestId]);

  const { data: detail } = usePolling<RequestDetail | null>({
    fetchFn: fetchDetail,
    interval: 5000,
  });

  if (!detail) {
    return (
      <div className="max-w-3xl mx-auto text-center py-10">
        <p className="text-gray-400">불러오는 중...</p>
      </div>
    );
  }

  const canCompose = detail.status === 'REQUESTED';

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">{detail.site_name}</h2>
        <button onClick={() => navigate('/office')} className="text-sm text-gray-500 hover:text-gray-800">
          ← 목록으로
        </button>
      </div>

      {/* 상태 + 액션 */}
      <div className="bg-white rounded-lg border border-gray-200 p-5 flex items-center justify-between">
        <div>
          <span className="text-sm text-gray-500">상태: </span>
          <span className="font-medium text-gray-800">{STATUS_LABEL[detail.status]}</span>
        </div>
        {canCompose && (
          <button
            onClick={() => navigate(`/office/compose/${requestId}`)}
            className="bg-purple-600 text-white px-4 py-2 rounded-md text-sm font-medium hover:bg-purple-700 transition-colors"
          >
            수동 편성하기
          </button>
        )}
      </div>

      {/* 요청 정보 */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <h3 className="text-sm font-medium text-gray-500 mb-3">요청 정보</h3>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-gray-500">작업일</span>
            <p className="font-medium text-gray-800">{detail.work_date}</p>
          </div>
          <div>
            <span className="text-gray-500">시작 시간</span>
            <p className="font-medium text-gray-800">{detail.start_time}</p>
          </div>
          <div className="col-span-2">
            <span className="text-gray-500">위치</span>
            <p className="font-medium text-gray-800">{detail.location_text}</p>
          </div>
          <div>
            <span className="text-gray-500">예산</span>
            <p className="font-medium text-gray-800">{detail.budget.toLocaleString()}원</p>
          </div>
          <div>
            <span className="text-gray-500">우선순위</span>
            <p className="font-medium text-gray-800 text-xs">
              비용 {PRIORITY_LABEL[detail.priority.cost]} / 숙련 {PRIORITY_LABEL[detail.priority.skill]} / 팀워크 {PRIORITY_LABEL[detail.priority.teamwork]}
            </p>
          </div>
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

      {/* 확정 작업조 */}
      {detail.crew && detail.crew.members.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-medium text-gray-500 mb-3">
            작업조 <span className="text-xs text-gray-400">({detail.crew.status})</span>
          </h3>
          <div className="space-y-2">
            {detail.crew.members.map((member: CrewMember) => (
              <div key={member.worker_id} className="flex items-center justify-between text-sm py-2 px-3 bg-purple-50 rounded">
                <div className="flex items-center gap-3">
                  <span className="font-medium text-gray-800">{member.name}</span>
                  <span className="text-xs text-gray-500">{TRADE_LABEL[member.trade] || member.trade}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-purple-600">숙련 {member.skill_level}</span>
                  <span className="text-xs text-gray-400">{member.desired_daily_wage.toLocaleString()}원</span>
                </div>
              </div>
            ))}
            <div className="flex justify-between text-sm pt-2 border-t border-gray-200 font-medium">
              <span>예상 총 비용</span>
              <span>{detail.crew.members.reduce((s, m) => s + m.desired_daily_wage, 0).toLocaleString()}원</span>
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
