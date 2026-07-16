'use client';

import { useMemo, useState, useTransition } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import type { Post } from '@/lib/types';
import { approveAndPublish, saveReportDraft } from '@/lib/actions';
import { btnCls, btnSecondaryCls, inputCls, labelCls, StatusBadge } from './ui';

const areaCls =
  'mt-1 w-full rounded-lg border border-line bg-surface-2 p-3 font-mono text-xs leading-relaxed text-fg shadow-card focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/25';

type Loc = { title: string; summary: string; body: string };

/** Report draft editor: one tab per language (design §4.8). Each language is
 * saved independently via a whitelist dot-path (saveReportDraft) so a language's
 * already-published notionPageId is never clobbered (design §6.2). */
export function ReportDraftEditor({ post }: { post: Post }) {
  const t = useTranslations('drafts');
  const tc = useTranslations('common');
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);

  const langs = useMemo(() => Object.keys(post.localizations ?? {}), [post.localizations]);
  const [lang, setLang] = useState(langs[0] ?? 'ja');
  const [loc, setLoc] = useState<Record<string, Loc>>(() => {
    const init: Record<string, Loc> = {};
    for (const l of langs) {
      const c = post.localizations?.[l];
      init[l] = { title: c?.title ?? '', summary: c?.summary ?? '', body: c?.body ?? '' };
    }
    return init;
  });
  const [selected, setSelected] = useState<string[]>(
    Object.entries(post.channels)
      .filter(([, ch]) => ch.enabled && ch.status === 'pending')
      .map(([name]) => name),
  );

  const cur: Loc = loc[lang] ?? { title: '', summary: '', body: '' };
  const setField = (field: keyof Loc, value: string) =>
    setLoc((prev) => ({ ...prev, [lang]: { ...prev[lang], [field]: value } }));

  function persist(l: string): FormData {
    const fd = new FormData();
    fd.set('id', post.id);
    fd.set('lang', l);
    fd.set('title', loc[l].title);
    fd.set('summary', loc[l].summary);
    fd.set('body', loc[l].body);
    return fd;
  }

  return (
    <div className="space-y-4">
      <div className="flex w-fit gap-1 rounded-lg border border-line bg-paper/60 p-1.5">
        {langs.map((l) => (
          <button
            key={l}
            onClick={() => setLang(l)}
            className={`rounded-lg px-4 py-1.5 font-mono text-xs font-medium transition-colors ${
              lang === l ? 'bg-surface text-fg shadow-card' : 'text-fg-muted hover:text-fg'
            }`}
          >
            {l}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2">
        <div className="space-y-4 rounded-xl border border-line bg-surface p-5 shadow-card">
          <label className={labelCls}>
            {tc('title')}
            <input value={cur.title} onChange={(e) => setField('title', e.target.value)} className={inputCls} />
          </label>
          <label className={labelCls}>
            {t('summary')}
            <textarea value={cur.summary} onChange={(e) => setField('summary', e.target.value)}
              rows={3} className={areaCls} />
          </label>
          <label className={labelCls}>
            {t('body')}
            <textarea value={cur.body} onChange={(e) => setField('body', e.target.value)}
              rows={24} className={areaCls} />
          </label>
          <button
            className={btnSecondaryCls}
            disabled={pending}
            onClick={() => startTransition(async () => {
              const res = await saveReportDraft(persist(lang));
              setResult(res.ok ? { ok: true, detail: tc('saved') } : res);
            })}
          >
            {`${tc('save')} (${lang})`}
          </button>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-line bg-surface p-5 shadow-card">
            <h2 className="mb-3 text-lg font-bold tracking-tight text-fg">{cur.title}</h2>
            <article className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
              {cur.body}
            </article>
          </div>

          <div className="rounded-xl border border-line bg-surface p-5 shadow-card">
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-fg-faint">
              {t('publishTo')}
            </div>
            <div className="mb-4 flex flex-wrap gap-2">
              {Object.entries(post.channels).map(([name, ch]) => {
                const checked = selected.includes(name);
                const locked = ch.status === 'published';
                return (
                  <label
                    key={name}
                    className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                      checked ? 'border-accent-line bg-accent-soft text-fg' : 'border-line bg-surface-2 text-fg-muted'
                    } ${locked ? 'cursor-not-allowed opacity-60' : ''}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={locked}
                      onChange={(e) => setSelected((prev) =>
                        e.target.checked ? [...prev, name] : prev.filter((n) => n !== name))}
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
                  for (const l of langs) {
                    const saved = await saveReportDraft(persist(l));
                    if (!saved.ok) {
                      setResult(saved);
                      return;
                    }
                  }
                  const res = await approveAndPublish(post.id, selected);
                  setResult(res);
                  if (res.ok) router.refresh();
                });
              }}
            >
              {pending ? '…' : t('approvePublish')}
            </button>
            {result && (
              <div className={`mt-3 rounded-lg px-3 py-2 font-mono text-xs ${
                result.ok ? 'bg-emerald-500/10 text-emerald-300' : 'bg-red-500/10 text-red-300'}`}>
                {result.detail.slice(0, 400)}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
