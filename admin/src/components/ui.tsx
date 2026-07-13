import type { ReactNode } from 'react';
import Link from 'next/link';

/* ---------- page scaffolding ---------- */

export function PageHeader({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
        {hint && <p className="mt-1 max-w-2xl text-sm leading-relaxed text-slate-500">{hint}</p>}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2 pt-1">{children}</div>}
    </header>
  );
}

export function Card({
  title,
  hint,
  actions,
  flush,
  children,
}: {
  title?: string;
  hint?: string;
  actions?: ReactNode;
  /** Remove inner padding (for full-bleed tables). */
  flush?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-line bg-white shadow-card">
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-3.5">
          <div>
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {hint && <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-slate-500">{hint}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={flush ? '' : 'p-5'}>{children}</div>
    </section>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center gap-1 py-10 text-center">
      <div className="text-2xl text-slate-300">∅</div>
      <p className="text-sm text-slate-400">{message}</p>
    </div>
  );
}

export function StatCard({
  label,
  value,
  sub,
  danger,
  footer,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  danger?: boolean;
  footer?: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-line bg-white p-5 shadow-card">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div
        className={`mt-2 font-mono text-3xl font-semibold tracking-tight ${
          danger ? 'text-red-600' : 'text-ink'
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
      {footer && <div className="mt-2 text-xs">{footer}</div>}
    </section>
  );
}

/* ---------- status ---------- */

const STATUS_STYLES: Record<string, { dot: string; cls: string }> = {
  draft: { dot: 'bg-amber-500', cls: 'bg-amber-50 text-amber-800 border-amber-200' },
  approved: { dot: 'bg-sky-500', cls: 'bg-sky-50 text-sky-800 border-sky-200' },
  publishing: { dot: 'bg-indigo-500', cls: 'bg-indigo-50 text-indigo-800 border-indigo-200' },
  published: { dot: 'bg-emerald-500', cls: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
  partially_published: {
    dot: 'bg-orange-500',
    cls: 'bg-orange-50 text-orange-800 border-orange-200',
  },
  failed: { dot: 'bg-red-500', cls: 'bg-red-50 text-red-700 border-red-200' },
  pending: { dot: 'bg-slate-400', cls: 'bg-slate-50 text-slate-600 border-slate-200' },
  skipped: { dot: 'bg-slate-300', cls: 'bg-slate-50 text-slate-400 border-slate-200' },
};

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.pending;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] font-medium ${s.cls}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${s.dot}`} />
      {status}
    </span>
  );
}

/** Neutral chip for enum-ish values that are not statuses (format, source type…). */
export function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-md border border-line bg-paper px-1.5 py-0.5 font-mono text-[11px] text-slate-600">
      {children}
    </span>
  );
}

export function EnabledBadge({ enabled, labels }: { enabled: boolean; labels: [string, string] }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${
        enabled
          ? 'border-accent-line bg-accent-soft text-accent'
          : 'border-slate-200 bg-slate-50 text-slate-400'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${enabled ? 'bg-accent' : 'bg-slate-300'}`} />
      {enabled ? labels[0] : labels[1]}
    </span>
  );
}

/* ---------- tables ---------- */

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">{children}</table>
    </div>
  );
}

export const thCls =
  'px-5 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400 bg-paper/60 border-b border-line whitespace-nowrap';
export const tdCls = 'px-5 py-3 border-b border-line/60 align-middle';

/* ---------- form + button class recipes ---------- */

export const inputCls =
  'mt-1 w-full rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink shadow-card placeholder:text-slate-300 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15';

export const labelCls = 'block text-[13px] font-medium text-slate-600';

export const btnCls =
  'inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3.5 py-2 text-sm font-semibold text-white shadow-card transition-colors hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40';

export const btnSecondaryCls =
  'inline-flex items-center justify-center gap-1.5 rounded-lg border border-line bg-white px-3.5 py-2 text-sm font-medium text-slate-700 shadow-card transition-colors hover:border-slate-300 hover:bg-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40';

export const btnDangerCls =
  'inline-flex items-center justify-center rounded-md px-2 py-1 text-xs font-medium text-red-600 transition-colors hover:bg-red-50 disabled:opacity-40';

export const linkCls = 'font-medium text-accent underline-offset-2 hover:underline';

export function TextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className={linkCls}>
      {children}
    </Link>
  );
}
