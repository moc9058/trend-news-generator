'use client';

import { useState } from 'react';
import { ActionButton } from './ActionButton';

const CHANNEL_SHORT: Record<string, string> = { x: 'X', threads: 'Threads', notion: 'Notion' };

/** Dashboard "manual run" card. The channel toggles are UI-only (they gate
 * which format buttons are clickable) — actual publish targets still come
 * from the saved channelConfigs, same as automated runs. X/Threads only
 * carry short-form posts, so article/report are disabled while either is
 * selected. */
export function ManualRunPanel({
  visibleChannels,
  shortLabel,
  articleLabel,
  reportLabel,
  hint,
  runShort,
  runArticle,
  runReport,
}: {
  visibleChannels: string[];
  shortLabel: string;
  articleLabel: string;
  reportLabel: string;
  hint: string;
  runShort: () => Promise<{ ok: boolean; detail: string }>;
  runArticle: () => Promise<{ ok: boolean; detail: string }>;
  runReport: () => Promise<{ ok: boolean; detail: string }>;
}) {
  const [channels, setChannels] = useState<string[]>(visibleChannels);
  const shortOnly = channels.includes('x') || channels.includes('threads');

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {visibleChannels.map((ch) => {
          const checked = channels.includes(ch);
          return (
            <label
              key={ch}
              className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-line bg-paper/60 px-1.5 py-0.5 text-[11px] text-slate-500 has-[:checked]:border-accent-line has-[:checked]:bg-accent-soft has-[:checked]:text-accent"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) =>
                  setChannels((prev) =>
                    e.target.checked ? [...prev, ch] : prev.filter((c) => c !== ch),
                  )
                }
                className="h-3 w-3 rounded border-line"
              />
              {CHANNEL_SHORT[ch] ?? ch}
            </label>
          );
        })}
      </div>
      <p className="text-xs text-slate-400">{hint}</p>
      <div className="flex flex-wrap gap-2.5">
        <ActionButton action={runShort} label={shortLabel} />
        <ActionButton action={runArticle} label={articleLabel} disabled={shortOnly} />
        <ActionButton action={runReport} label={reportLabel} disabled={shortOnly} />
      </div>
    </div>
  );
}
