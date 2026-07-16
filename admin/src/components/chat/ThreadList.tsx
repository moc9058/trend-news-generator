'use client';

/** The conversation history rail: threads grouped by recency, each with its
 *  time, turn count and cost, plus rename / archive / delete. Reads come from a
 *  server component (the `threads` prop); the management actions are server
 *  actions that revalidate, so a change here re-renders the rail in place. */

import { useMemo, useRef, useState, useTransition } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';
import { Icon } from '@/components/icons';
import { archiveChatThread, deleteChatThread, renameChatThread } from '@/lib/actions';
import { btnSecondaryCls } from '@/components/ui';
import type { ChatThread } from '@/lib/types';

export interface ThreadListLabels {
  newChat: string;
  noThreads: string;
  noMatches: string;
  untitled: string;
  search: string;
  today: string;
  yesterday: string;
  thisWeek: string;
  earlier: string;
  rename: string;
  archive: string;
  delete: string;
  confirmDelete: string;
  save: string;
  cancel: string;
}

const DAY = 86_400_000;

function startOfToday(now: number): number {
  const d = new Date(now);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function bucketOf(iso: string | undefined, now: number, labels: ThreadListLabels): string {
  if (!iso) return labels.earlier;
  const t = new Date(iso).getTime();
  const today = startOfToday(now);
  if (t >= today) return labels.today;
  if (t >= today - DAY) return labels.yesterday;
  if (t >= today - 7 * DAY) return labels.thisWeek;
  return labels.earlier;
}

/** Compact, instrument-style relative time: 5m · 3h · 2d, then a short date. */
function relTime(iso: string | undefined, now: number): string {
  if (!iso) return '';
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86_400) return `${Math.floor(s / 3600)}h`;
  if (s < 7 * 86_400) return `${Math.floor(s / 86_400)}d`;
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function ThreadList({
  threads,
  activeId,
  locale,
  labels,
}: {
  threads: ChatThread[];
  activeId?: string;
  locale: string;
  labels: ThreadListLabels;
}) {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [menuId, setMenuId] = useState('');
  const [editingId, setEditingId] = useState('');
  const [draft, setDraft] = useState('');
  const [confirmId, setConfirmId] = useState('');
  const [, startTransition] = useTransition();
  const now = useRef(Date.now()).current;

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = q
      ? threads.filter((t) => (t.title || labels.untitled).toLowerCase().includes(q))
      : threads;
    const order = [labels.today, labels.yesterday, labels.thisWeek, labels.earlier];
    const byBucket = new Map<string, ChatThread[]>();
    for (const t of rows) {
      const b = bucketOf(t.lastMessageAt, now, labels);
      byBucket.set(b, [...(byBucket.get(b) ?? []), t]);
    }
    return order
      .filter((b) => byBucket.has(b))
      .map((b) => ({ bucket: b, items: byBucket.get(b)! }));
  }, [threads, query, now, labels]);

  const closeMenus = () => {
    setMenuId('');
    setConfirmId('');
  };

  const submitRename = (id: string) => {
    const title = draft.trim();
    setEditingId('');
    if (!title) return;
    startTransition(async () => {
      await renameChatThread(id, title);
    });
  };

  const onArchive = (id: string) => {
    closeMenus();
    startTransition(async () => {
      await archiveChatThread(id);
    });
  };

  const onDelete = (id: string) => {
    closeMenus();
    startTransition(async () => {
      await deleteChatThread(id);
      if (id === activeId) router.push(`/${locale}/chat`);
    });
  };

  const hasThreads = threads.length > 0;

  return (
    <div className="space-y-2">
      <Link href={`/${locale}/chat`} className={`${btnSecondaryCls} w-full`}>
        <Icon name="chat" size={13} />
        {labels.newChat}
      </Link>

      {hasThreads && (
        <div className="relative">
          <Icon
            name="search"
            size={13}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={labels.search}
            className="w-full rounded-lg border border-line bg-surface-2 py-1.5 pl-8 pr-2.5 text-xs text-fg placeholder:text-fg-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25"
          />
        </div>
      )}

      {!hasThreads ? (
        <p className="px-1 py-2 text-xs text-fg-faint">{labels.noThreads}</p>
      ) : groups.length === 0 ? (
        <p className="px-1 py-2 text-xs text-fg-faint">{labels.noMatches}</p>
      ) : (
        <div className="space-y-3">
          {groups.map(({ bucket, items }) => (
            <div key={bucket}>
              <div className="mb-1 px-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-faint">
                {bucket}
              </div>
              <ul className="space-y-0.5">
                <AnimatePresence initial={false}>
                  {items.map((th) => {
                    const active = th.id === activeId;
                    const editing = editingId === th.id;
                    const cost = th.totals?.costUsd ?? 0;
                    const msgs = th.totals?.messages ?? 0;
                    return (
                      <motion.li
                        key={th.id}
                        layout
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, height: 0, transition: { duration: 0.16 } }}
                        className="relative"
                      >
                        {editing ? (
                          <div className="flex items-center gap-1 rounded-lg border border-accent-line bg-surface-2 px-1.5 py-1">
                            <input
                              autoFocus
                              value={draft}
                              onChange={(e) => setDraft(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') submitRename(th.id);
                                if (e.key === 'Escape') setEditingId('');
                              }}
                              className="min-w-0 flex-1 bg-transparent text-xs text-fg focus:outline-none"
                            />
                            <button
                              type="button"
                              onClick={() => submitRename(th.id)}
                              aria-label={labels.save}
                              className="rounded p-1 text-accent hover:bg-accent-soft"
                            >
                              <Icon name="check" size={13} />
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingId('')}
                              aria-label={labels.cancel}
                              className="rounded p-1 text-fg-faint hover:bg-surface-3 hover:text-fg"
                            >
                              <Icon name="close" size={13} />
                            </button>
                          </div>
                        ) : (
                          <div
                            className={`group flex items-start gap-1 rounded-lg pr-1 transition-colors ${
                              active
                                ? 'bg-accent-soft ring-1 ring-inset ring-accent-line'
                                : 'hover:bg-surface-2'
                            }`}
                          >
                            <Link
                              href={`/${locale}/chat/${th.id}`}
                              className="min-w-0 flex-1 px-2.5 py-1.5"
                            >
                              <div
                                className={`truncate text-xs ${
                                  active ? 'font-medium text-accent' : 'text-fg'
                                }`}
                              >
                                {th.title || labels.untitled}
                              </div>
                              <div className="mt-0.5 flex items-center gap-1.5 font-mono text-[10px] text-fg-faint">
                                <span suppressHydrationWarning>{relTime(th.lastMessageAt, now)}</span>
                                {msgs > 0 && <span>· {msgs}</span>}
                                {cost > 0 && <span>· ${cost.toFixed(2)}</span>}
                              </div>
                            </Link>
                            <button
                              type="button"
                              onClick={() => setMenuId(menuId === th.id ? '' : th.id)}
                              aria-label={labels.rename}
                              className={`mt-1 shrink-0 rounded p-1 text-fg-faint transition-opacity hover:bg-surface-3 hover:text-fg focus:opacity-100 ${
                                menuId === th.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                              }`}
                            >
                              <Icon name="more" size={14} />
                            </button>
                          </div>
                        )}

                        {menuId === th.id && !editing && (
                          <div className="absolute right-1 top-full z-20 mt-0.5 w-36 overflow-hidden rounded-lg border border-line bg-surface-3 py-1 text-xs shadow-raised">
                            {confirmId === th.id ? (
                              <div className="px-2.5 py-1.5">
                                <p className="mb-1.5 text-[11px] text-fg-muted">
                                  {labels.confirmDelete}
                                </p>
                                <div className="flex gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() => onDelete(th.id)}
                                    className="flex-1 rounded bg-red-600/90 px-2 py-1 text-[11px] font-medium text-white hover:bg-red-600"
                                  >
                                    {labels.delete}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setConfirmId('')}
                                    className="flex-1 rounded border border-line px-2 py-1 text-[11px] text-fg-muted hover:bg-surface-2"
                                  >
                                    {labels.cancel}
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setDraft(th.title || '');
                                    setEditingId(th.id);
                                    closeMenus();
                                  }}
                                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-fg-muted hover:bg-surface-2 hover:text-fg"
                                >
                                  <Icon name="drafts" size={13} />
                                  {labels.rename}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => onArchive(th.id)}
                                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-fg-muted hover:bg-surface-2 hover:text-fg"
                                >
                                  <Icon name="archive" size={13} />
                                  {labels.archive}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setConfirmId(th.id)}
                                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-red-300 hover:bg-red-500/10"
                                >
                                  <Icon name="trash" size={13} />
                                  {labels.delete}
                                </button>
                              </>
                            )}
                          </div>
                        )}
                      </motion.li>
                    );
                  })}
                </AnimatePresence>
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
