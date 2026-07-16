'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/** Polls the server component tree on an interval by calling router.refresh().
 * The layout is force-dynamic, so each refresh re-reads Firestore — this is how
 * the approval page reflects a report run's progress (and its finished draft)
 * without a client Firebase SDK / onSnapshot. Only mount with enabled=true while
 * something is actually in progress, so an idle page never polls. */
export function AutoRefresh({ enabled, intervalMs = 5000 }: { enabled: boolean; intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [enabled, intervalMs, router]);
  return null;
}
