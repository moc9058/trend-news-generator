import type { ChatSource } from '@/lib/types';

const TIER_CLS: Record<string, string> = {
  primary: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  secondary: 'bg-sky-50 text-sky-700 ring-sky-600/20',
  tertiary: 'bg-slate-100 text-slate-600 ring-slate-500/20',
};

/** Numbered citation list under an answer; [n] matches the body's markers. */
export function SourceList({ sources, label }: { sources: ChatSource[]; label: string }) {
  if (!sources.length) return null;
  return (
    <div className="mt-3 border-t border-line/60 pt-3">
      <p className="mb-2 text-xs font-semibold text-slate-500">{label}</p>
      <ol className="space-y-1.5">
        {sources.map((s) => (
          <li key={s.n} className="flex items-start gap-2 text-xs leading-relaxed">
            <span className="mt-px shrink-0 font-mono text-slate-400">[{s.n}]</span>
            <span className="min-w-0">
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-accent underline-offset-2 hover:underline"
              >
                {s.title || s.url}
              </a>
              <span className="ml-1.5 inline-flex items-center gap-1 align-middle">
                {s.tier && (
                  <span
                    className={`rounded px-1 py-px text-[10px] font-medium ring-1 ring-inset ${
                      TIER_CLS[s.tier] ?? TIER_CLS.tertiary
                    }`}
                  >
                    {s.tier}
                  </span>
                )}
                {typeof s.score === 'number' && s.score > 0 && (
                  <span className="font-mono text-[10px] text-slate-400">{s.score}</span>
                )}
              </span>
              <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-400">
                {s.url}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
