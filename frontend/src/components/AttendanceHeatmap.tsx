import type { AttendanceMap } from '../api/types';

// GitHub 잔디 스타일 출근일 히트맵. 최근 약 4개월(17주)을 주 단위 열로 표시한다.
const WEEKS = 17;

function toKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export default function AttendanceHeatmap({ attendance }: { attendance: AttendanceMap }) {
  const end = new Date();
  end.setHours(0, 0, 0, 0);
  // 시작: 오늘 기준 WEEKS*7일 전, 그 주의 일요일로 정렬
  const start = new Date(end);
  start.setDate(end.getDate() - (WEEKS * 7 - 1));
  start.setDate(start.getDate() - start.getDay()); // 일요일로

  const weeks: { key: string; count: number; future: boolean }[][] = [];
  const cursor = new Date(start);
  while (cursor <= end || weeks.length === 0 || weeks[weeks.length - 1].length < 7) {
    const week = weeks.length === 0 || weeks[weeks.length - 1].length === 7 ? [] : weeks[weeks.length - 1];
    if (week.length === 0) weeks.push(week);
    const key = toKey(cursor);
    week.push({ key, count: attendance[key] || 0, future: cursor > end });
    cursor.setDate(cursor.getDate() + 1);
    if (cursor > end && week.length === 7) break;
  }

  const total = Object.values(attendance).filter((count) => count > 0).length;

  return (
    <div>
      <div className="grid grid-flow-col grid-rows-7 gap-1 w-full pb-1">
        {weeks.map((week, wi) => (
          <div key={wi} className="contents">
            {week.map((cell) => (
              <div
                key={cell.key}
                aria-hidden={cell.future}
                aria-label={cell.future ? undefined : `${cell.key} ${cell.count ? '근무함' : '근무하지 않음'}`}
                tabIndex={cell.count ? 0 : undefined}
                className={`relative group w-full aspect-square rounded-sm ${cell.future ? 'bg-transparent' : cell.count ? 'bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-400' : 'bg-gray-100'}`}
              >
                {cell.count > 0 && (
                  <span className="pointer-events-none absolute z-20 hidden group-hover:block group-focus:block bottom-full left-1/2 -translate-x-1/2 mb-1 whitespace-nowrap rounded bg-gray-900 px-2 py-1 text-[10px] text-white shadow-lg">
                    {cell.key} · 근무함
                  </span>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between mt-2 text-[11px] text-gray-400">
        <span>최근 약 4개월 · 근무 {total}일</span>
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-sm bg-gray-100 inline-block" />
          기록 없음
          <span className="w-2.5 h-2.5 rounded-sm bg-green-600 inline-block ml-1" />
          근무함
        </span>
      </div>
    </div>
  );
}
