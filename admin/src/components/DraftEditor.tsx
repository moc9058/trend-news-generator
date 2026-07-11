'use client';

import { useMemo, useState, useTransition } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import type { Post } from '@/lib/types';
import { approveAndPublish, saveDraft } from '@/lib/actions';
import { THREADS_LIMIT, X_LIMIT, xWeightedLength } from '@/lib/textLimits';
import { btnCls, btnSecondaryCls, inputCls } from './ui';

const areaCls =
  'w-full rounded border border-slate-300 p-2 font-mono text-xs focus:border-slate-500 focus:outline-none';

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
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <div className="space-y-3">
        <label className="block text-sm">
          {tc('title')}
          <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputCls} />
        </label>
        <label className="block text-sm">
          {t('summary')}
          <textarea value={summary} onChange={(e) => setSummary(e.target.value)}
            rows={3} className={areaCls} />
        </label>
        <label className="block text-sm">
          {t('body')}
          <textarea value={body} onChange={(e) => setBody(e.target.value)}
            rows={24} className={areaCls} />
        </label>
        <div className="space-y-2">
          <div className="text-sm font-medium">{t('channelTexts')}</div>
          <label className="block text-xs">
            {t('xText')}
            <span className={`ml-2 ${xLen > X_LIMIT ? 'text-red-600' : 'text-slate-400'}`}>
              {t('xWeighted', { count: xLen })}
            </span>
            <textarea value={xText} onChange={(e) => setXText(e.target.value)}
              rows={4} className={areaCls} />
          </label>
          <label className="block text-xs">
            {t('threadsText')}
            <span className={`ml-2 ${threadsText.length > THREADS_LIMIT ? 'text-red-600' : 'text-slate-400'}`}>
              {t('charCount', { count: threadsText.length })}/{THREADS_LIMIT}
            </span>
            <textarea value={threadsText} onChange={(e) => setThreadsText(e.target.value)}
              rows={4} className={areaCls} />
          </label>
        </div>
        <div className="flex items-center gap-3">
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
      </div>

      <div className="space-y-3">
        <div className="flex gap-1">
          {(['notion', 'x', 'threads'] as const).map((name) => (
            <button key={name}
              onClick={() => setTab(name)}
              className={`rounded-t px-3 py-1.5 text-sm ${
                tab === name ? 'bg-white font-medium shadow-sm' : 'bg-slate-100 text-slate-500'
              }`}
            >
              {name} {t('preview')}
            </button>
          ))}
        </div>
        <div className="min-h-64 rounded-lg border border-slate-200 bg-white p-4">
          {tab === 'notion' && (
            <article className="prose prose-sm max-w-none whitespace-pre-wrap text-sm">
              <h2 className="mb-2 text-base font-bold">{title}</h2>
              {body}
            </article>
          )}
          {tab === 'x' && (
            <div className="max-w-md rounded-xl border border-slate-200 p-3 text-sm whitespace-pre-wrap">
              {xText}
              {post.cadence !== 'daily' && (
                <div className="mt-1 text-xs text-sky-600">+ Notion URL</div>
              )}
            </div>
          )}
          {tab === 'threads' && (
            <div className="max-w-md rounded-xl border border-slate-200 p-3 text-sm whitespace-pre-wrap">
              {threadsText}
              {post.cadence !== 'daily' && (
                <div className="mt-1 text-xs text-sky-600">+ Notion URL</div>
              )}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-2 text-sm font-medium">{t('publishTo')}</div>
          <div className="mb-3 flex gap-4">
            {Object.entries(post.channels).map(([name, ch]) => (
              <label key={name} className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(name)}
                  disabled={ch.status === 'published'}
                  onChange={(e) =>
                    setSelected((prev) =>
                      e.target.checked ? [...prev, name] : prev.filter((n) => n !== name),
                    )
                  }
                />
                {name}
                {ch.status !== 'pending' && (
                  <span className="text-xs text-slate-400">({ch.status})</span>
                )}
              </label>
            ))}
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
            <div className={`mt-2 text-xs ${result.ok ? 'text-emerald-700' : 'text-red-700'}`}>
              {result.detail.slice(0, 400)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
