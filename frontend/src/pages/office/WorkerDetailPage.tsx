import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../../api/client';
import type { Worker } from '../../api/types';
import { tradeLabel } from '../../lib/trades';

const STATE_LABEL: Record<string, string> = {
  INACTIVE: '비활성', READY: '대기 중', NOTIFIED: '제안 중', RESERVED: '배차 확정', RUNNING: '작업 중',
};

export default function WorkerDetailPage() {
  const navigate = useNavigate();
  const { workerId } = useParams();
  const [worker, setWorker] = useState<Worker | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!workerId) return;
    setLoading(true);
    const response = await api.get<Worker>(`/office/workers/${workerId}`);
    if (response.success) {
      setWorker(response.data);
      setError('');
    } else {
      setError(response.error.message);
    }
    setLoading(false);
  }, [workerId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <p className="text-center text-gray-400 py-10">지원서를 불러오는 중...</p>;
  if (!worker) {
    return (
      <div className="max-w-3xl mx-auto text-center py-10">
        <p className="text-red-600 mb-4">{error || '근로자 정보를 찾을 수 없습니다.'}</p>
        <button onClick={() => navigate('/office/workers')} className="text-sm text-purple-700">← 근로자 목록</button>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-purple-600 font-medium">근로자 지원서</p>
          <h2 className="text-xl font-semibold text-gray-800">{worker.name}</h2>
        </div>
        <button onClick={() => navigate('/office/workers')} className="text-sm text-gray-500 hover:text-gray-800">← 목록으로</button>
      </div>

      <section className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center justify-between mb-5">
          <h3 className="font-semibold text-gray-800">기본 정보</h3>
          <span className="text-xs bg-purple-50 text-purple-700 px-2.5 py-1 rounded-full">
            {STATE_LABEL[worker.state] || worker.state}
          </span>
        </div>
        <dl className="grid grid-cols-2 md:grid-cols-3 gap-5 text-sm">
          <Info label="연락처" value={worker.phone} />
          <Info label="나이" value={`${worker.age}세`} />
          <Info label="지역" value={worker.region} />
          <Info label="경력" value={`${worker.career_years}년`} />
          <Info label="희망 일당" value={`${worker.desired_daily_wage.toLocaleString()}원`} />
          <Info label="완료 작업" value={`${worker.completed_count}건`} />
        </dl>
      </section>

      <section className="bg-white rounded-lg border border-gray-200 p-6 space-y-5">
        <TagSection title="희망 직종" items={worker.preferred_trades.map(tradeLabel)} color="green" />
        <TagSection title="비희망 직종" items={worker.excluded_trades.map(tradeLabel)} color="red" />
        <TagSection title="자격증" items={worker.certifications} color="green" empty="등록한 자격증이 없습니다." />
        <TagSection title="보유 작업 능력" items={worker.abilities || []} color="blue" empty="등록한 작업 능력이 없습니다." />
        <div>
          <h3 className="text-sm font-medium text-gray-500 mb-2">자기소개</h3>
          <p className="text-sm text-gray-800 whitespace-pre-wrap bg-gray-50 rounded-md p-4">
            {worker.introduction || '작성한 자기소개가 없습니다.'}
          </p>
        </div>
      </section>

      <section className="bg-white rounded-lg border border-gray-200 p-6">
        <h3 className="text-sm font-medium text-gray-500 mb-3">완료 작업 이력 ({worker.work_history.length})</h3>
        {worker.work_history.length === 0 ? (
          <p className="text-sm text-gray-400">완료된 작업이 없습니다.</p>
        ) : (
          <div className="divide-y divide-gray-100">
            {worker.work_history.map((entry) => (
              <div key={`${entry.crew_id}-${entry.work_date}`} className="py-3 flex items-center justify-between text-sm">
                <div>
                  <p className="font-medium text-gray-800">{entry.site_name}</p>
                  <p className="text-xs text-gray-500">{entry.work_date} · {tradeLabel(entry.assigned_trade)}</p>
                </div>
                <span className="text-gray-700">{entry.offered_wage.toLocaleString()}원</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-gray-500 mb-1">{label}</dt>
      <dd className="font-medium text-gray-800">{value}</dd>
    </div>
  );
}

function TagSection({ title, items, color, empty }: { title: string; items: string[]; color: 'green' | 'red' | 'blue'; empty?: string }) {
  const colors = {
    green: 'bg-green-50 text-green-700', red: 'bg-red-50 text-red-700', blue: 'bg-blue-50 text-blue-700',
  };
  return (
    <div>
      <h3 className="text-sm font-medium text-gray-500 mb-2">{title}</h3>
      {items.length ? (
        <div className="flex flex-wrap gap-2">
          {items.map((item) => <span key={item} className={`text-xs px-2.5 py-1 rounded-full ${colors[color]}`}>{item}</span>)}
        </div>
      ) : <p className="text-sm text-gray-400">{empty || '없음'}</p>}
    </div>
  );
}
