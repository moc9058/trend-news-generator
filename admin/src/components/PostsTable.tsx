'use client';

import { useState, useTransition } from 'react';
import Link from 'next/link';
import { deletePosts } from '@/lib/actions';
import { Icon } from './icons';
import { Chip, EmptyState, StatusBadge, tdCls, thCls } from './ui';

export type PostRow = {
  id: string;
  status: string;
  title: string;
  format: string;
  categoryId: string;
  createdAt: string;
  costUsd: number | null;
  channels: { name: string; status: string; url?: string }[];
};

export function PostsTable({
  posts,
  locale,
  labels,
}: {
  posts: PostRow[];
  locale: string;
  labels: {
    status: string;
    title: string;
    format: string;
    channels: string;
    cost: string;
    created: string;
    empty: string;
    deleteSelected: string;
    confirmDelete: string;
    selected: string;
  };
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState('');

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };
  const allChecked = posts.length > 0 && checked.size === posts.length;

  if (posts.length === 0) return <EmptyState message={labels.empty} />;

  return (
    <div>
      {checked.size > 0 && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line bg-amber-50/70 px-5 py-2.5">
          <span className="text-xs font-medium text-slate-600">
            {labels.selected.replace('{count}', String(checked.size))}
          </span>
          <button
            disabled={pending}
            onClick={() => {
              if (!window.confirm(labels.confirmDelete)) return;
              startTransition(async () => {
                const result = await deletePosts([...checked]);
                if (!result.ok) setError(result.detail);
                else {
                  setError('');
                  setChecked(new Set());
                }
              });
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-700 disabled:opacity-40"
          >
            {pending ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent opacity-60" />
            ) : (
              <Icon name="trash" size={13} />
            )}
            {labels.deleteSelected}
          </button>
          {error && <span className="font-mono text-xs text-red-600">{error.slice(0, 160)}</span>}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className={`${thCls} w-10`}>
                <input
                  type="checkbox"
                  checked={allChecked}
                  onChange={() =>
                    setChecked(allChecked ? new Set() : new Set(posts.map((p) => p.id)))
                  }
                  className="h-4 w-4 rounded border-line"
                />
              </th>
              <th className={thCls}>{labels.status}</th>
              <th className={thCls}>{labels.title}</th>
              <th className={thCls}>{labels.channels}</th>
              <th className={thCls}>{labels.cost}</th>
              <th className={thCls}>{labels.created}</th>
            </tr>
          </thead>
          <tbody>
            {posts.map((p) => (
              <tr key={p.id} className="transition-colors hover:bg-paper/50">
                <td className={tdCls}>
                  <input
                    type="checkbox"
                    checked={checked.has(p.id)}
                    onChange={() => toggle(p.id)}
                    className="h-4 w-4 rounded border-line"
                  />
                </td>
                <td className={tdCls}>
                  <StatusBadge status={p.status} />
                </td>
                <td className={`${tdCls} max-w-xs`}>
                  <Link
                    href={`/${locale}/posts/${p.id}`}
                    className="block truncate text-[13px] font-medium text-ink underline-offset-2 hover:text-accent hover:underline"
                  >
                    {p.title || p.id}
                  </Link>
                  <div className="mt-0.5 flex items-center gap-1.5 font-mono text-[11px] text-slate-400">
                    <Chip>{p.format}</Chip>
                    {p.categoryId}
                  </div>
                </td>
                <td className={tdCls}>
                  <div className="flex flex-wrap gap-x-3 gap-y-1">
                    {p.channels.map((ch) => (
                      <span key={ch.name} className="inline-flex items-center gap-1.5 text-xs">
                        <span className="font-mono text-slate-500">{ch.name}</span>
                        <StatusBadge status={ch.status} />
                        {ch.url && (
                          <a
                            href={ch.url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-accent hover:opacity-70"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Icon name="external" size={12} />
                          </a>
                        )}
                      </span>
                    ))}
                  </div>
                </td>
                <td className={`${tdCls} whitespace-nowrap font-mono text-xs text-slate-500`}>
                  {p.costUsd !== null ? `$${p.costUsd.toFixed(3)}` : '—'}
                </td>
                <td className={`${tdCls} whitespace-nowrap font-mono text-xs text-slate-400`}>
                  {p.createdAt.slice(0, 16).replace('T', ' ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
