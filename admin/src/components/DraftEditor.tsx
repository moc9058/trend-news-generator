'use client';

import { useMemo, useState, useTransition } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import type { Post } from '@/lib/types';
import { approveAndPublish, saveDraft } from '@/lib/actions';
import { THREADS_LIMIT, X_LIMIT, xWeightedLength } from '@/lib/textLimits';
import { btnCls, btnSecondaryCls, inputCls, labelCls, StatusBadge } from './ui';

const areaCls =
  'mt-1 w-full rounded-lg border border-line bg-white p-3 font-mono text-xs leading-relaxed text-ink shadow-card focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15';

function LimitMeter({ count, limit }: { count: number; limit: number }) {
  const over = count > limit;
  const pct = Math.min(100, (count / limit) * 100);
  return (
    <span className="ml-auto inline-flex items-center gap-2">
      <span className="h-1 w-16 overflow-hidden rounded-full bg-slate-200">
        <span
          className={`block h-full rounded-full ${over ? 'bg-red-500' : 'bg-accent'}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className={`font-mono text-[11px] ${over ? 'font-semibold text-red-600' : 'text-slate-400'}`}>
        {count}/{limit}
      </span>
    </span>
  );
}

export function DraftEditor({ post }: { post: Post }) {
  const t = useTranslations('drafts');
  const tc = useTranslations('common');
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);
  const [tab, setTab] = useState<'x' | 'threads' | 'notion'>('notion');

  const [title, setTitle] = useState(post.title);
  const [summary, setSummary] = useState(post.summary);
  const [body, setBody] = useState(post.body);
  const [xText, setXText] = useState(post.channels.x?.text ?? '');
  const [threadsText, setThreadsText] = useState(post.channels.threads?.text ?? '');
  const [selected, setSelected] = useState<string[]>(
    Object.entries(post.channels)
      .filter(([, ch]) => ch.enabled && ch.status === 'pending')
      .map(([name]) => name),
  );

  const xLen = useMemo(() => xWeightedLength(xText), [xText]);

  function persist(): FormData {
    const fd = new FormData();
    fd.set('id', post.id);
    fd.set('title', title);
    fd.set('summary', summary);
    fd.set('body', body);
    fd.set('xText', xText);
    fd.set('threadsText', threadsText);
    return fd;
  }

  return (
    <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2">
      {/* editor column */}
      <div className="space-y-4 rounded-xl border border-line bg-white p-5 shadow-card">
        <label className={labelCls}>
          {tc('title')}
          <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} />
        </label>
        <label className={labelCls}>
          {t('summary')}
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)}
            rows={3} className={areaCls} />
        </label>
        <label className={labelCls}>
          {t('body')}
          <textarea value={body} onChange={(e) => setBody(e.target.value)}
            rows={24} className={areaCls} />
        </label>

        <div className="space-y-3 border-t border-line pt-4">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            {t('channelTexts')}
          </div>
          <label className={labelCls}>
            <span className="flex items-center">
              {t('xText')}
              <LimitMeter count={xLen} limit={X_LIMIT} />
            </span>
            <textarea value={xText} onChange={(e) => setXText(e.target.value)}
              rows={4} className={areaCls} />
          </label>
          <label className={labelCls}>
            <span className="flex items-center">
              {t('threadsText')}
              <LimitMeter count={threadsText.length} limit={THREADS_LIMIT} />
            </span>
            <textarea value={threadsText} onChange={(e) => setThreadsText(e.target.value)}
              rows={4} className={areaCls} />
          </label>
        </div>

        <button
          className={btnSecondaryCls}
          disabled={pending}
          onClick={() => startTransition(async () => {
            await saveDraft(persist());
            setResult({ ok: true, detail: 'saved' });
          })}
        >
          {tc('save')}
        </button>
      </div>

      {/* preview + publish column */}
      <div className="space-y-4">
        <div className="overflow-hidden rounded-xl border border-line bg-white shadow-card">
          <div className="flex gap-1 border-b border-line bg-paper/60 p-1.5">
            {(['notion', 'x', 'threads'] as const).map((name) => (
              <button
                key={name}
                onClick={() => setTab(name)}
                className={`flex-1 rounded-lg px-3 py-1.5 font-mono text-xs font-medium transition-colors ${
                  tab === name
                    ? 'bg-white text-ink shadow-card'
                    : 'text-slate-500 hover:text-ink'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
          <div className="min-h-64 p-5">
            {tab === 'notion' && (
              <article className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                <h2 className="mb-3 text-lg font-bold tracking-tight text-ink">{title}</h2>
                {body}
              </article>
            )}
            {tab !== 'notion' && (
              <div className="mx-auto max-w-md rounded-xl border border-line bg-paper/40 p-4">
                <div className="mb-2.5 flex items-center gap-2.5">
                  <div className="h-8 w-8 rounded-full bg-ink" />
                  <div className="leading-tight">
                    <div className="text-[13px] font-semibold text-ink">Trend News</div>
                    <div className="font-mono text-[11px] text-slate-400">
                      @trendnews · {tab}
                    </div>
                  </div>
                </div>
                <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                  {tab === 'x' ? xText : threadsText}
                </div>
                {post.format !== 'short' && (
                  <div className="mt-2 font-mono text-xs text-accent">+ Notion URL</div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-line bg-white p-5 shadow-card">
          <div className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            {t('publishTo')}
          </div>
          <div className="mb-4 flex flex-wrap gap-2">
            {Object.entries(post.channels).map(([name, ch]) => {
              const checked = selected.includes(name);
              const locked = ch.status === 'published';
              return (
                <label
                  key={name}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors ${
                    checked
                      ? 'border-accent-line bg-accent-soft text-ink'
                      : 'border-line bg-white text-slate-500'
                  } ${locked ? 'cursor-not-allowed opacity-60' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={locked}
                    onChange={(e) =>
                      setSelected((prev) =>
                        e.target.checked ? [...prev, name] : prev.filter((n) => n !== name),
                      )
                    }
                    className="h-4 w-4 rounded border-line"
                  />
                  <span className="font-mono text-xs font-medium">{name}</span>
                  {ch.status !== 'pending' && <StatusBadge status={ch.status} />}
                </label>
              );
            })}
          </div>
          <button
            className={btnCls}
            disabled={pending || selected.length === 0}
            onClick={() => {
              if (!window.confirm(t('confirmPublish'))) return;
              startTransition(async () => {
                await saveDraft(persist());
                const res = await approveAndPublish(post.id, selected);
                setResult(res);
                if (res.ok) router.refresh();
              });
            }}
          >
            {pending ? '…' : t('approvePublish')}
          </button>
          {result && (
            <div
              className={`mt-3 rounded-lg px-3 py-2 font-mono text-xs ${
                result.ok ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'
              }`}
            >
              {result.detail.slice(0, 400)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
