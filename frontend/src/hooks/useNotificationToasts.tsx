import { useEffect, useRef } from 'react';
import toast from 'react-hot-toast';
import { api } from '../api/client';
import type { Notification } from '../api/types';

// 알림을 폴링하여 안 읽은 알림을 toast로 띄우고 읽음 처리
export function useNotificationToasts(enabled: boolean) {
  const shownIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!enabled) return;
    let active = true;

    const poll = async () => {
      const res = await api.get<Notification[]>('/notifications');
      if (!active || !res.success) return;

      const unread = res.data.filter((n) => !n.read && !shownIds.current.has(n.id));
      if (unread.length === 0) return;

      // 오래된 순으로 최대 5개만 표시 (스팸 방지)
      // 읽음 처리는 하지 않음 → 알림함(종 아이콘)에서 안 읽음으로 계속 표시됨
      const toShow = unread.slice(0, 5);
      for (const n of toShow) {
        shownIds.current.add(n.id);
        toast(
          (t) => (
            <div
              onClick={() => toast.dismiss(t.id)}
              className="cursor-pointer"
            >
              <p className="font-medium text-sm text-gray-800">🔔 {n.title}</p>
              <p className="text-xs text-gray-500 mt-0.5">{n.message}</p>
            </div>
          ),
          { duration: 6000 }
        );
      }
    };

    poll();
    const timer = window.setInterval(poll, 4000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [enabled]);
}
