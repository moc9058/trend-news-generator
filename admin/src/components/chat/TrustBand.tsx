'use client';

/** The trust band: one tick per source, in citation order.
 *
 *   fill   = tier   (primary solid / secondary half / tertiary dashed outline)
 *   height = score, drawn against SCORE_SCALE
 *
 * No hue. The admin's rule is that colour means status (amber=draft,
 * green=published), and a tier is not a status — so the trust scale is encoded
 * in ink density and height instead. On the dark canvas that density runs the
 * other way (bright = primary), against the foreground colour. Cyan stays
 * reserved for interaction.
 *
 * While a research run is still reading, sources have no grades yet (the SSE
 * `sources` event lands just before the prose streams), so the band shows plain
 * ticks that resolve into graded bars, which dock in as the batch arrives. That
 * resolution IS the product's claim: it read them, then it graded them.
 */

import { AnimatePresence, motion } from 'framer-motion';
import type { ChatSource } from '@/lib/types';

/** Chat calls rubric.score_reliability(sourceType, url) with no corroboration,
 * recency or author signals, so a score is only base + venue_authority. The
 * real ceiling is a Diet record at 55 (base 40 + .go.jp 15); arXiv lands at 42,
 * Reuters at 33, an unknown blog at 15. Drawing those against 100 would render
 * every answer as a row of stubs and read as "weak evidence" when it is in fact
 * the best this rubric can award. 60 is the honest scale. */
export const SCORE_SCALE = 60;

const TIER_FILL: Record<string, string> = {
  primary: 'bg-fg border-fg',
  secondary: 'bg-fg/40 border-fg/50',
  tertiary: 'border-dashed border-fg/50 bg-transparent',
};

export function TrustBand({
  sources,
  pendingCount = 0,
  litN,
  onLit,
  label,
}: {
  sources: ChatSource[];
  /** Ungraded ticks to show while reading, before grades arrive. */
  pendingCount?: number;
  litN?: number | null;
  onLit?: (n: number | null) => void;
  label: string;
}) {
  if (!sources.length && pendingCount > 0) {
    return (
      <div className="flex h-[26px] items-end gap-[3px]" aria-label={label}>
        {Array.from({ length: pendingCount }, (_, i) => (
          <span
            key={i}
            className="h-1.5 w-3.5 animate-pulse border border-fg/20 bg-fg/10"
          />
        ))}
      </div>
    );
  }
  if (!sources.length) return null;

  return (
    <ul className="flex h-[26px] items-end gap-[3px] p-0" aria-label={label}>
      <AnimatePresence initial={false}>
        {sources.map((s, i) => {
          const pct = Math.max(
            8,
            Math.round((Math.min(s.score ?? 0, SCORE_SCALE) / SCORE_SCALE) * 100),
          );
          const lit = litN === s.n;
          return (
            <motion.li
              key={s.n}
              className="flex h-full items-end"
              initial={{ opacity: 0, scaleY: 0.35 }}
              animate={{ opacity: 1, scaleY: 1 }}
              style={{ transformOrigin: 'bottom' }}
              transition={{ duration: 0.24, delay: Math.min(i, 12) * 0.02, ease: 'easeOut' }}
            >
              <button
                type="button"
                // Square on purpose: the card around it is rounded-2xl, but a
                // measurement is not rounded.
                className={`w-3.5 border transition-transform ${
                  TIER_FILL[s.tier ?? 'tertiary'] ?? TIER_FILL.tertiary
                } ${lit ? '-translate-y-0.5 ring-2 ring-accent' : ''} focus-visible:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent`}
                style={{ height: `${pct}%` }}
                title={`[${s.n}] ${s.title || s.url} — ${s.tier} ${s.score}/${SCORE_SCALE}`}
                aria-label={`[${s.n}] ${s.title || s.url} — ${s.tier} ${s.score}/${SCORE_SCALE}`}
                onMouseEnter={() => onLit?.(s.n)}
                onMouseLeave={() => onLit?.(null)}
                onFocus={() => onLit?.(s.n)}
                onBlur={() => onLit?.(null)}
              />
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ul>
  );
}
