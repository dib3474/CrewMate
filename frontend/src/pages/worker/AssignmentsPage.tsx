import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { usePolling } from '../../hooks/usePolling';

interface Assignment {
  crew_id: string;
  request_id: string;
  site_name: string;
  work_date: string;
  start_time: string;
  location_text: string;
  status: string;
}

const STATUS_LABEL: Record<string, { label: string; color: string }> = {
  APPROVED: { label: '승인됨', color: 'bg-blue-100 text-blue-700' },
  RUNNING: { label: '작업 중', color: 'bg-orange-100 text-orange-700' },
  COMPLETED: { label: '완료', color: 'bg-green-100 text-green-700' },
};

export default function AssignmentsPage() {
  const navigate = useNavigate();

  const fetchAssignments = useCallback(async () => {
    const res = await api.get<Assignment[]>('/worker/assignments');
    if (res.success) return res.data;
    return [];
  }, []);

  const { data: assignments, loading } = usePolling<Assignment[]>({
    fetchFn: fetchAssignments,
    interval: 5000,
  });

  return (
    <div className="max-w-lg mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-800">배정 정보</h2>
        <button
          onClick={() => navigate('/worker')}
          className="text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          ← 돌아가기
        </button>
      </div>

      {loading && !assignments && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center">
          <p className="text-gray-400">불러오는 중...</p>
        </div>
      )}

      {assignments && assignments.length === 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-6 text-center">
          <p className="text-gray-500">현재 배정된 작업이 없습니다.</p>
        </div>
      )}

      {assignments && assignments.map((assignment) => {
        const statusInfo = STATUS_LABEL[assignment.status] || { label: assignment.status, color: 'bg-gray-100 text-gray-700' };

        return (
          <div key={assignment.crew_id} className="bg-white rounded-lg border border-gray-200 p-6">
            {/* 상태 뱃지 */}
            <div className="flex items-center justify-between mb-4">
              <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${statusInfo.color}`}>
                {statusInfo.label}
              </span>
              <span className="text-xs text-gray-400">{assignment.crew_id}</span>
            </div>

            {/* 현장 정보 */}
            <div className="space-y-3">
              <div>
                <p className="text-lg font-semibold text-gray-800">{assignment.site_name}</p>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span className="text-gray-500">작업일</span>
                  <p className="font-medium text-gray-800">{assignment.work_date}</p>
                </div>
                <div>
                  <span className="text-gray-500">시작 시간</span>
                  <p className="font-medium text-gray-800">{assignment.start_time}</p>
                </div>
              </div>

              <div className="text-sm">
                <span className="text-gray-500">위치</span>
                <p className="font-medium text-gray-800">{assignment.location_text}</p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
