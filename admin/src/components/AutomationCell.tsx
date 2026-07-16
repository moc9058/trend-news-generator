'use client';

import { useState } from 'react';

/** One category x format cell in the dashboard automation grid. When the
 * generate-on checkbox is off, the channel checkboxes below it are visually
 * disabled (they stay in the DOM and still submit their current value, so
 * saved channel preferences survive re-enabling generation later). */
export function AutomationCell({
  id,
  generateLabel,
  generateDefaultChecked,
  channels,
  channelDefaults,
  channelShortLabels,
}: {
  id: string;
  generateLabel: string;
  generateDefaultChecked: boolean;
  channels: string[];
  channelDefaults: Record<string, boolean>;
  channelShortLabels: Record<string, string>;
}) {
  const [enabled, setEnabled] = useState(generateDefaultChecked);

  return (
    <div className="space-y-1.5">
      <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium text-fg-muted">
        <input
          type="checkbox"
          name={`enabled_${id}`}
          defaultChecked={generateDefaultChecked}
          onChange={(e) => setEnabled(e.target.checked)}
          className="h-4 w-4 rounded border-line"
        />
        {generateLabel}
      </label>
      <div
        className={`flex flex-wrap gap-1 transition-opacity ${
          enabled ? '' : 'pointer-events-none opacity-40'
        }`}
        aria-disabled={!enabled}
      >
        {channels.map((ch) => (
          <label
            key={ch}
            className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-line bg-paper/60 px-1.5 py-0.5 text-[11px] text-fg-muted has-[:checked]:border-accent-line has-[:checked]:bg-accent-soft has-[:checked]:text-accent"
          >
            <input
              type="checkbox"
              name={`ch_${id}_${ch}`}
              defaultChecked={channelDefaults[ch] ?? false}
              tabIndex={enabled ? 0 : -1}
              className="h-3 w-3 rounded border-line"
            />
            {channelShortLabels[ch]}
          </label>
        ))}
      </div>
    </div>
  );
}
