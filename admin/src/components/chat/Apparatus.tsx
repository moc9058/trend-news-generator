'use client';

/** The numbered sources under a research answer — a scholarly apparatus, not a
 * chat citation chip row.
 *
 * Deliberately absent: a "Sources" heading (a numbered column of links is
 * self-evident), the connector name (the host already says it), the full URL
 * (it is behind the link), and tier colour badges (the band encodes tier).
 *
 * Tier stays the raw Latin enum in mono, matching how this admin already shows
 * `draft` / `published` — enum values are not translated here.
 */

import { SCORE_SCALE } from './TrustBand';
import type { ChatSource } from '@/lib/types';

function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

export function Apparatus({
  sources,
  litN,
  onLit,
}: {
  sources: ChatSource[];
  litN?: number | null;
  onLit?: (n: number | null) => void;
}) {
  if (!sources.length) return null;
  return (
    <ol className="mt-3 grid gap-1.5 border-t border-line/60 pt-3 font-mono text-[11.5px] leading-relaxed">
      {sources.map((s) => (
        <li
          key={s.n}
          className={`grid grid-cols-[1.4rem_2rem_minmax(0,1fr)] items-baseline gap-2.5 ${
            litN === s.n ? 'bg-accent-soft/60' : ''
          }`}
          onMouseEnter={() => onLit?.(s.n)}
          onMouseLeave={() => onLit?.(null)}
        >
          <span className="text-slate-400">[{s.n}]</span>
          <span className="text-right font-semibold tabular-nums text-ink">
            {s.score}
            <span className="text-slate-400">/{SCORE_SCALE}</span>
          </span>
          <span className="min-w-0">
            <a
              href={s.url}
              target="_blank"
              rel="noreferrer"
              className="font-sans text-ink underline-offset-2 hover:text-accent hover:underline"
            >
              {s.title || s.url}
            </a>
            <span className="ml-1.5 whitespace-nowrap text-slate-400">
              {host(s.url)} · {s.tier}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}
