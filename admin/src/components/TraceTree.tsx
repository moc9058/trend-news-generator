'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Chip } from './ui';
import type { TraceSpan } from '@/lib/langsmith';

/* Nesting is drawn with a left indent rather than collapsible subtrees: a
   report run is a shallow, mostly-linear graph, and flattening keeps the
   chronological read (dotted_order) that the phase timeline above shares. */
const INDENT_PX = 14;
const MAX_INDENT_DEPTH = 6;

function duration(ms: number | null): string {
  if (ms === null) return '';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export function TraceTree({ spans, clipped }: { spans: TraceSpan[]; clipped: boolean }) {
  const t = useTranslations('research');
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div>
      {clipped && (
        <div className="border-b border-line/60 px-5 py-2 text-xs text-amber-300">
          {t('traceClipped', { count: spans.length })}
        </div>
      )}
      <ul className="divide-y divide-line/60">
        {spans.map((s) => {
          const expanded = open === s.id;
          const payload = s.inputs || s.outputs;
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : s.id)}
                disabled={!payload}
                className="flex w-full items-center gap-3 px-5 py-2 text-left text-sm hover:bg-paper disabled:cursor-default disabled:hover:bg-transparent"
              >
                <span
                  className="shrink-0"
                  style={{ paddingLeft: Math.min(s.depth, MAX_INDENT_DEPTH) * INDENT_PX }}
                >
                  <Chip>{s.runType}</Chip>
                </span>
                <span className={`truncate ${s.error ? 'text-red-300' : 'text-fg'}`}>{s.name}</span>
                {s.error && <span className="truncate text-xs text-red-300">{s.error}</span>}
                <span className="ml-auto flex shrink-0 items-center gap-3 font-mono text-[11px] text-fg-faint">
                  {(s.tokensIn > 0 || s.tokensOut > 0) && <span>{s.tokensIn}→{s.tokensOut}</span>}
                  {s.costUsd > 0 && <span>${s.costUsd.toFixed(3)}</span>}
                  <span className="w-12 text-right text-fg-muted">{duration(s.durationMs)}</span>
                </span>
              </button>

              {expanded && (
                <div className="space-y-3 bg-paper px-5 pb-4 pt-1">
                  {s.inputs && <Payload label={t('traceInputs')} body={s.inputs} />}
                  {s.outputs && <Payload label={t('traceOutputs')} body={s.outputs} />}
                  <div className="flex items-center gap-3">
                    {s.truncated && <span className="text-[11px] text-amber-300">{t('traceTruncated')}</span>}
                    {s.url && (
                      <a href={s.url} target="_blank" rel="noreferrer"
                        className="text-[11px] font-medium text-accent underline-offset-2 hover:underline">
                        {t('traceOpenSpan')}
                      </a>
                    )}
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Payload({ label, body }: { label: string; body: string }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">{label}</div>
      <pre className="max-h-72 overflow-auto rounded-lg border border-line bg-surface p-3 font-mono text-[11px] leading-relaxed text-fg whitespace-pre-wrap">
        {body}
      </pre>
    </div>
  );
}
