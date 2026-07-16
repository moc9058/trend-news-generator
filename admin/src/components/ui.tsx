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
        <h1 className="bg-gradient-to-r from-fg to-fg/70 bg-clip-text text-2xl font-bold tracking-tight text-transparent">
          {title}
        </h1>
        {hint && <p className="mt-1 max-w-2xl text-sm leading-relaxed text-fg-muted">{hint}</p>}
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
    <section className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card transition-shadow hover:shadow-raised">
      {(title || actions) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-gradient-to-r from-surface-2/40 to-transparent px-5 py-3.5">
          <div>
            {title && <h2 className="text-sm font-semibold tracking-tight text-fg">{title}</h2>}
            {hint && <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-fg-muted">{hint}</p>}
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
      <div className="text-2xl text-fg-faint">∅</div>
      <p className="text-sm text-fg-muted">{message}</p>
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
    <section className="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 shadow-card transition-shadow hover:shadow-raised">
      <span
        className={`absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r ${
          danger ? 'from-red-500 to-transparent' : 'from-accent to-transparent'
        }`}
        aria-hidden
      />
      <div className="text-[11px] font-semibold uppercase tracking-wider text-fg-faint">
        {label}
      </div>
      <div
        className={`mt-2 font-mono text-3xl font-semibold tracking-tight ${
          danger ? 'text-red-400' : 'text-fg'
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-fg-muted">{sub}</div>}
      {footer && <div className="mt-2 text-xs">{footer}</div>}
    </section>
  );
}

/* ---------- status ---------- */

/* Dark translucent tints: a low-alpha fill, a mid-alpha border, a bright-300
 * label, a solid -400 dot. Hue keeps its meaning (amber=draft, emerald=done,
 * red=failed); `approved`/`running` use blue/indigo so status colour stays
 * distinct from the cyan *interaction* accent. */
const STATUS_STYLES: Record<string, { dot: string; cls: string }> = {
  draft: { dot: 'bg-amber-400', cls: 'bg-amber-500/10 text-amber-300 border-amber-500/30' },
  approved: { dot: 'bg-blue-400', cls: 'bg-blue-500/10 text-blue-300 border-blue-500/30' },
  publishing: { dot: 'bg-indigo-400', cls: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30' },
  published: { dot: 'bg-emerald-400', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' },
  partially_published: {
    dot: 'bg-orange-400',
    cls: 'bg-orange-500/10 text-orange-300 border-orange-500/30',
  },
  failed: { dot: 'bg-red-400', cls: 'bg-red-500/10 text-red-300 border-red-500/30' },
  pending: { dot: 'bg-slate-400', cls: 'bg-slate-500/10 text-slate-300 border-slate-500/25' },
  skipped: { dot: 'bg-slate-500', cls: 'bg-slate-500/10 text-slate-400 border-slate-500/20' },
  deleted: {
    dot: 'bg-slate-500',
    cls: 'bg-slate-500/10 text-slate-400 border-slate-500/25 line-through',
  },
  // research run statuses
  queued: { dot: 'bg-slate-400', cls: 'bg-slate-500/10 text-slate-300 border-slate-500/25' },
  running: { dot: 'bg-indigo-400', cls: 'bg-indigo-500/10 text-indigo-300 border-indigo-500/30' },
  awaiting_plan_approval: {
    dot: 'bg-amber-400',
    cls: 'bg-amber-500/10 text-amber-300 border-amber-500/30',
  },
  awaiting_review: { dot: 'bg-amber-400', cls: 'bg-amber-500/10 text-amber-300 border-amber-500/30' },
  completed: { dot: 'bg-emerald-400', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30' },
  cancelled: { dot: 'bg-slate-500', cls: 'bg-slate-500/10 text-slate-400 border-slate-500/20' },
  budget_exhausted: {
    dot: 'bg-orange-400',
    cls: 'bg-orange-500/10 text-orange-300 border-orange-500/30',
  },
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
    <span className="inline-flex items-center rounded-md border border-line bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">
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
          : 'border-line bg-surface-2 text-fg-faint'
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${enabled ? 'bg-accent' : 'bg-fg-faint'}`} />
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
  'px-5 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wider text-fg-faint bg-surface-2/50 border-b border-line whitespace-nowrap';
export const tdCls = 'px-5 py-3 border-b border-line/60 align-middle';

/* ---------- form + button class recipes ---------- */

export const inputCls =
  'mt-1 w-full rounded-lg border border-line bg-surface-2 px-3 py-2 text-sm text-fg shadow-card placeholder:text-fg-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25';

export const labelCls = 'block text-[13px] font-medium text-fg-muted';

export const btnCls =
  'inline-flex items-center justify-center gap-1.5 rounded-xl bg-accent px-3.5 py-2 text-sm font-semibold text-accent-contrast shadow-card transition-all hover:bg-accent-hover hover:shadow-raised active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40';

export const btnSecondaryCls =
  'inline-flex items-center justify-center gap-1.5 rounded-xl border border-line bg-surface-2 px-3.5 py-2 text-sm font-medium text-fg shadow-card transition-all hover:border-accent-line hover:bg-accent-soft hover:text-accent active:scale-[0.98] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-40';

export const btnDangerCls =
  'inline-flex items-center justify-center rounded-md px-2 py-1 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-40';

export const linkCls = 'font-medium text-accent underline-offset-2 hover:underline';

export function TextLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className={linkCls}>
      {children}
    </Link>
  );
}
