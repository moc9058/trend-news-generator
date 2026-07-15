'use client';

/** "Send to drafting" under a finished assistant answer.
 *
 * Whatever this creates is a draft (short/article) or a queued research run
 * (report) — never a published post. Publishing stays on the approvals screen.
 */

import { useState, useTransition } from 'react';
import Link from 'next/link';
import { handoffChat } from '@/lib/actions';
import type { Category, ChatHandoffRef } from '@/lib/types';
import { btnCls, btnSecondaryCls, inputCls, labelCls, linkCls } from '@/components/ui';

export interface HandoffLabels {
  handoff: string;
  handoffShort: string;
  handoffArticle: string;
  handoffReport: string;
  handoffCategory: string;
  handoffTheme: string;
  handoffSubmit: string;
  handoffDone: string;
  handoffOpenDraft: string;
  handoffOpenRun: string;
  handoffNote: string;
}

function refHref(format: string, refId: string, locale: string): string {
  return format === 'report' ? `/${locale}/research/${refId}` : `/${locale}/drafts/${refId}`;
}

export function HandoffMenu({
  threadId, messageId, categories, labels, locale, handoffs,
}: {
  threadId: string;
  messageId: string;
  categories: Category[];
  labels: HandoffLabels;
  locale: string;
  handoffs: ChatHandoffRef[];
}) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState('short');
  const [categoryId, setCategoryId] = useState(categories[0]?.slug ?? '');
  const [theme, setTheme] = useState('');
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const [created, setCreated] = useState<{ format: string; refId: string } | null>(null);

  const submit = () => {
    const fd = new FormData();
    fd.set('threadId', threadId);
    fd.set('messageId', messageId);
    fd.set('format', format);
    fd.set('categoryId', categoryId);
    fd.set('theme', theme);
    startTransition(async () => {
      const r = await handoffChat(fd);
      setResult(r);
      if (r.ok) {
        try {
          const parsed = JSON.parse(r.detail) as { refId?: string };
          if (parsed.refId) setCreated({ format, refId: parsed.refId });
        } catch {
          // A non-JSON success body still counts as success; just no deep link.
        }
        setOpen(false);
      }
    });
  };

  const existing = [...handoffs, ...(created ? [created as ChatHandoffRef] : [])];

  return (
    <div className="mt-2 border-t border-line/60 pt-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="text-xs font-medium text-slate-500 transition-colors hover:text-accent"
          onClick={() => setOpen((v) => !v)}
        >
          {labels.handoff}
        </button>
        {existing.map((h) => (
          <Link
            key={`${h.format}-${h.refId}`}
            href={refHref(h.format, h.refId, locale)}
            className={`${linkCls} text-xs`}
          >
            {h.format === 'report' ? labels.handoffOpenRun : labels.handoffOpenDraft}
          </Link>
        ))}
        {result && !result.ok && (
          <span className="font-mono text-xs text-red-600">{result.detail.slice(0, 160)}</span>
        )}
      </div>

      {open && (
        <div className="mt-2 space-y-2 rounded-lg border border-line bg-paper/30 p-3">
          <div className="flex flex-wrap gap-1">
            {(
              [
                ['short', labels.handoffShort],
                ['article', labels.handoffArticle],
                ['report', labels.handoffReport],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setFormat(value)}
                aria-pressed={format === value}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                  format === value
                    ? 'bg-accent-soft text-accent ring-1 ring-inset ring-accent-line'
                    : 'text-slate-500 hover:bg-white'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {format !== 'report' && (
            <label className="block">
              <span className={labelCls}>{labels.handoffCategory}</span>
              <select
                className={inputCls}
                value={categoryId}
                onChange={(e) => setCategoryId(e.target.value)}
              >
                {categories.map((c) => (
                  <option key={c.slug} value={c.slug}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {format === 'report' && (
            <label className="block">
              <span className={labelCls}>{labels.handoffTheme}</span>
              <input
                className={inputCls}
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
              />
            </label>
          )}

          <p className="text-[11px] leading-relaxed text-slate-500">{labels.handoffNote}</p>

          <div className="flex items-center gap-2">
            <button type="button" className={btnCls} onClick={submit} disabled={pending}>
              {pending && (
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent opacity-60" />
              )}
              {labels.handoffSubmit}
            </button>
            <button type="button" className={btnSecondaryCls} onClick={() => setOpen(false)}>
              ✕
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
