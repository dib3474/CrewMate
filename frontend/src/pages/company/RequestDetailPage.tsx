import { useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';
import type { WorkRequest, WorkRequestStatus, Crew, CrewMember } from '../../api/types';

const STATUS_STEPS: WorkRequestStatus[] = ['REQUESTED', 'COMPOSING', 'PROPOSED', 'APPROVED', 'RUNNING', 'COMPLETED'];

const STATUS_LABEL: Record<string, string> = {
  REQUESTED: '요청됨',
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

export default function RequestDetailPage() {
  const { requestId } = useParams<{ requestId: string }>();
  const navigate = useNavigate();

  const fetchDetail = useCallback(async () => {
    if (!requestId) return null;
    const res = await api.get<RequestDetail>(`/company/requests/${requestId}`);
    if (res.success) return res.data;
    return null;
  }, [requestId]);

  const { data: detail, loading } = usePolling<RequestDetail | null>({
    fetchFn: fetchDetail,
    interval: 5000,
  });

  if (loading && !detail) {
    return (
      <div className="max-w-2xl mx-auto">
        <p className="text-gray-400 text-center py-10">불러오는 중...</p>
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="max-w-2xl mx-auto text-center py-10">
        <p className="text-gray-500">요청을 찾을 수 없습니다.</p>
        <button
          onClick={() => navigate('/company')}
          className="text-orange-600 text-sm hover:underline mt-2"
        >
          목록으로 돌아가기
        </button>
      </div>
    );
  }

  const currentStepIdx = STATUS_STEPS.indexOf(detail.status);

  return (
    <div className="max-w-2xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">{detail.site_name}</h2>
        <button
          onClick={() => navigate('/company')}
          className="text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          ← 목록으로
        </button>
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
                  <div
                    className={`w-full h-2 rounded-full ${
                      isActive ? 'bg-orange-500' : 'bg-gray-200'
                    } ${isCurrent ? 'animate-pulse' : ''}`}
                  />
                  <span className={`text-[10px] mt-1 ${isActive ? 'text-orange-600 font-medium' : 'text-gray-400'}`}>
                    {STATUS_LABEL[step]}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

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
              비용: {PRIORITY_LABEL[detail.priority.cost]} / 숙련: {PRIORITY_LABEL[detail.priority.skill]} / 팀워크: {PRIORITY_LABEL[detail.priority.teamwork]}
            </p>
          </div>
        </div>
        {detail.notes && (
          <div className="mt-3 pt-3 border-t border-gray-100 text-sm">
            <span className="text-gray-500">비고</span>
            <p className="text-gray-800">{detail.notes}</p>
          </div>
        )}
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
          <div className="flex items-center justify-between text-sm pt-2 border-t border-gray-200 font-medium">
            <span>합계</span>
            <span>{detail.required_workers.reduce((s, w) => s + w.count, 0)}명</span>
          </div>
        </div>
      </div>

      {/* 확정 작업조 (PRD: 이름·직종·숙련도만) */}
      {detail.crew && detail.crew.members.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-medium text-gray-500 mb-3">확정 작업조</h3>
          <div className="space-y-2">
            {detail.crew.members.map((member: CrewMember) => (
              <div key={member.worker_id} className="flex items-center justify-between text-sm py-2 px-3 bg-orange-50 rounded">
                <div className="flex items-center gap-3">
                  <span className="font-medium text-gray-800">{member.name}</span>
                  <span className="text-xs text-gray-500">{TRADE_LABEL[member.trade] || member.trade}</span>
                </div>
                <span className="text-xs text-orange-600">숙련 {member.skill_level}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
