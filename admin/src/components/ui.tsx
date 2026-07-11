import type { ReactNode } from 'react';

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {title && <h2 className="mb-3 text-sm font-semibold text-slate-700">{title}</h2>}
      {children}
    </section>
  );
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-amber-100 text-amber-800',
  approved: 'bg-sky-100 text-sky-800',
  publishing: 'bg-indigo-100 text-indigo-800',
  published: 'bg-emerald-100 text-emerald-800',
  partially_published: 'bg-orange-100 text-orange-800',
  failed: 'bg-red-100 text-red-800',
  pending: 'bg-slate-100 text-slate-600',
  skipped: 'bg-slate-100 text-slate-400',
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        STATUS_COLORS[status] ?? 'bg-slate-100 text-slate-600'
      }`}
    >
      {status}
    </span>
  );
}

export const inputCls =
  'w-full rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-slate-500 focus:outline-none';
export const btnCls =
  'rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50';
export const btnSecondaryCls =
  'rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50';
