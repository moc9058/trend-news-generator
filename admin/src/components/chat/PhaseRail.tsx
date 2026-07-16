'use client';

/** The live "dispatch" instrument shown under a streaming research answer: the
 *  six research phases as a stepper, plus the connector / host / count detail
 *  the SSE `status` events already carry (planning → searching → selecting →
 *  reading → [gap_check, deep only] → synthesizing).
 *
 *  Deterministic: it only reflects `state.progress`. No phase is inferred and no
 *  LLM is involved — the stage the server reports is the stage that lights up. */

import { AnimatePresence, motion } from 'framer-motion';
import type { ChatLabels } from './ChatView';
import type { ChatStage, StreamProgress } from './useChatStream';

const ORDER: ChatStage[] = [
  'planning',
  'searching',
  'selecting',
  'reading',
  'gap_check',
  'synthesizing',
];

const STAGE_LABEL: Record<ChatStage, keyof ChatLabels> = {
  planning: 'statusPlanning',
  searching: 'statusSearching',
  selecting: 'statusSelecting',
  reading: 'statusReading',
  gap_check: 'statusGapCheck',
  synthesizing: 'statusSynthesizing',
};

function host(url?: string): string {
  if (!url) return '';
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

export function PhaseRail({
  progress,
  labels,
  deep,
}: {
  progress: StreamProgress;
  labels: ChatLabels;
  deep: boolean;
}) {
  // gap_check only runs on deep research; hide the step otherwise.
  const steps = ORDER.filter((s) => deep || s !== 'gap_check');
  const active = steps.indexOf(progress.stage);

  const detail =
    progress.stage === 'searching'
      ? [progress.connector, progress.query].filter(Boolean).join(' · ')
      : progress.stage === 'reading'
        ? host(progress.url)
        : '';
  const count = typeof progress.count === 'number' && progress.count > 0 ? progress.count : null;

  return (
    <div className="mt-3 flex flex-col gap-2 rounded-lg border border-line bg-surface-2/40 px-3 py-2">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-1.5">
        {steps.map((s, i) => {
          const state = i < active ? 'done' : i === active ? 'active' : 'todo';
          return (
            <li key={s} className="flex items-center gap-1">
              <span
                className={`h-1.5 w-1.5 rounded-full transition-colors ${
                  state === 'active'
                    ? 'bg-accent animate-pulse'
                    : state === 'done'
                      ? 'bg-accent/60'
                      : 'bg-fg-faint/40'
                }`}
              />
              <span
                className={`font-mono text-[10px] uppercase tracking-[0.08em] transition-colors ${
                  state === 'active'
                    ? 'text-accent'
                    : state === 'done'
                      ? 'text-fg-muted'
                      : 'text-fg-faint'
                }`}
              >
                {labels[STAGE_LABEL[s]]}
              </span>
              {i < steps.length - 1 && (
                <span
                  className={`ml-0.5 h-px w-2.5 transition-colors ${
                    i < active ? 'bg-accent/40' : 'bg-line'
                  }`}
                />
              )}
            </li>
          );
        })}
      </ol>
      <AnimatePresence mode="wait" initial={false}>
        {(detail || count) && (
          <motion.div
            key={progress.stage + detail}
            initial={{ opacity: 0, y: -3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="flex min-w-0 items-center gap-1.5 font-mono text-[10.5px] text-fg-muted"
          >
            {detail && <span className="min-w-0 truncate">{detail}</span>}
            {count && <span className="shrink-0 text-fg-faint">· {count}</span>}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
