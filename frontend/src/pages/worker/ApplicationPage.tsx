import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import type { Worker, WorkerApplicationRequest, Trade } from '../../api/types';

const TRADE_OPTIONS: { value: Trade; label: string }[] = [
  { value: 'FORMWORK', label: '형틀목공' },
  { value: 'REBAR', label: '철근공' },
  { value: 'MASONRY', label: '조적공' },
  { value: 'MATERIAL_CARRY', label: '자재운반' },
  { value: 'GENERAL', label: '보통인부' },
];

const OFFICE_OPTIONS = [
  { value: 'OFFICE001', label: '부산인력사무소' },
  { value: 'OFFICE002', label: '김해인력사무소' },
];

export default function ApplicationPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [isEdit, setIsEdit] = useState(false);
  const [form, setForm] = useState<WorkerApplicationRequest>({
    name: '',
    phone: '',
    office_id: 'OFFICE001',
    trade: 'GENERAL',
    skill_level: 3,
    career_years: 0,
    age: 20,
    region: '',
    desired_daily_wage: 150000,
    certifications: [],
    introduction: '',
  });
  const [certInput, setCertInput] = useState('');

  // 기존 데이터 불러오기
  useEffect(() => {
    (async () => {
      const res = await api.get<Worker>('/worker/me');
      if (res.success && res.data.name) {
        const w = res.data;
        setIsEdit(true);
        setForm({
          name: w.name,
          phone: w.phone,
          office_id: w.office_id,
          trade: w.trade,
          skill_level: w.skill_level,
          career_years: w.career_years,
          age: w.age,
          region: w.region,
          desired_daily_wage: w.desired_daily_wage,
          certifications: w.certifications,
        });
      }
    })();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    const method = isEdit ? api.put : api.post;
    const res = await method<Worker>('/worker/application', form);

    setLoading(false);

    if (res.success) {
      navigate('/worker');
    } else {
      alert(res.error.message);
    }
  };

  const addCertification = () => {
    if (certInput.trim() && !form.certifications.includes(certInput.trim())) {
      setForm({ ...form, certifications: [...form.certifications, certInput.trim()] });
      setCertInput('');
    }
  };

  const removeCertification = (cert: string) => {
    setForm({ ...form, certifications: form.certifications.filter((c) => c !== cert) });
  };

  return (
    <div className="max-w-lg mx-auto">
      <h2 className="text-xl font-semibold text-gray-800 mb-6">
        {isEdit ? '지원서 수정' : '지원서 작성'}
      </h2>

      <form onSubmit={handleSubmit} className="bg-white rounded-lg border border-gray-200 p-6 space-y-5">
        {/* 이름 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">이름 *</label>
          <input
            type="text"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
            placeholder="홍길동"
          />
        </div>

        {/* 전화번호 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">전화번호 *</label>
          <input
            type="tel"
            required
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
            placeholder="010-1234-5678"
          />
        </div>

        {/* 인력사무소 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">인력사무소 *</label>
          <select
            value={form.office_id}
            onChange={(e) => setForm({ ...form, office_id: e.target.value })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          >
            {OFFICE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* 분야 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">분야 (직종) *</label>
          <select
            value={form.trade}
            onChange={(e) => setForm({ ...form, trade: e.target.value as Trade })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          >
            {TRADE_OPTIONS.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </div>

        {/* 숙련도 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            숙련도 * <span className="text-gray-400">(1~5)</span>
          </label>
          <input
            type="number"
            min={1}
            max={5}
            required
            value={form.skill_level}
            onChange={(e) => setForm({ ...form, skill_level: Number(e.target.value) })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </div>

        {/* 경력 연차 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">경력 (년) *</label>
          <input
            type="number"
            min={0}
            required
            value={form.career_years}
            onChange={(e) => setForm({ ...form, career_years: Number(e.target.value) })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </div>

        {/* 나이 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">나이 *</label>
          <input
            type="number"
            min={18}
            max={70}
            required
            value={form.age}
            onChange={(e) => setForm({ ...form, age: Number(e.target.value) })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </div>

        {/* 지역 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">지역 *</label>
          <input
            type="text"
            required
            value={form.region}
            onChange={(e) => setForm({ ...form, region: e.target.value })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
            placeholder="부산 해운대구"
          />
        </div>

        {/* 희망 일당 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">희망 일당 (원) *</label>
          <input
            type="number"
            min={100000}
            step={10000}
            required
            value={form.desired_daily_wage}
            onChange={(e) => setForm({ ...form, desired_daily_wage: Number(e.target.value) })}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
          />
        </div>

        {/* 자격증 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">자격증</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={certInput}
              onChange={(e) => setCertInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCertification(); } }}
              className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
              placeholder="자격증명 입력 후 추가"
            />
            <button
              type="button"
              onClick={addCertification}
              className="px-3 py-2 bg-gray-100 text-gray-700 rounded-md text-sm hover:bg-gray-200"
            >
              추가
            </button>
          </div>
          {form.certifications.length > 0 && (
            <div className="flex flex-wrap gap-2 mt-2">
              {form.certifications.map((cert) => (
                <span key={cert} className="inline-flex items-center gap-1 bg-green-50 text-green-700 text-xs px-2 py-1 rounded-full">
                  {cert}
                  <button type="button" onClick={() => removeCertification(cert)} className="text-green-500 hover:text-green-800">×</button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* 자기소개 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">자기소개</label>
          <textarea
            value={form.introduction || ''}
            onChange={(e) => setForm({ ...form, introduction: e.target.value })}
            rows={3}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
            placeholder="간단한 자기소개를 입력해주세요."
          />
        </div>

        {/* 제출 */}
        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={loading}
            className="flex-1 bg-green-600 text-white py-2.5 rounded-md text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
          >
            {loading ? '저장 중...' : isEdit ? '수정 완료' : '지원서 제출'}
          </button>
          <button
            type="button"
            onClick={() => navigate('/worker')}
            className="px-4 py-2.5 border border-gray-300 text-gray-700 rounded-md text-sm hover:bg-gray-50 transition-colors"
          >
            취소
          </button>
        </div>
      </form>
    </div>
  );
}
