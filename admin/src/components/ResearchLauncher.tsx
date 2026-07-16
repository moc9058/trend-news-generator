'use client';

import { useState, useTransition } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { launchResearchRun } from '@/lib/actions';
import { btnCls, inputCls, labelCls } from './ui';

/** New-run form. A client component because it needs its own submit state and the
 * plain ActionButton cannot carry input fields (P6). Empty theme = auto-select. */
export function ResearchLauncher({ categories }: { categories: { slug: string; name: string }[] }) {
  const t = useTranslations('research');
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);

  return (
    <form
      action={(fd) => startTransition(async () => {
        const res = await launchResearchRun(fd);
        setResult(res);
        if (res.ok) router.refresh();
      })}
      className="space-y-4"
    >
      <label className={labelCls}>
        {t('theme')}
        <input name="theme" className={inputCls} placeholder={t('themePlaceholder')} />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className={labelCls}>
          {t('category')}
          <select name="categoryId" defaultValue="" className={inputCls}>
            <option value="">{t('autoCategory')}</option>
            {categories.map((c) => (
              <option key={c.slug} value={c.slug}>{c.name}</option>
            ))}
          </select>
        </label>
        <label className={labelCls}>
          {t('budget')}
          <input name="budgetUsd" type="number" min="1" max="30" step="1"
            defaultValue="10" className={inputCls} />
        </label>
      </div>
      <label className="flex items-center gap-2.5 text-sm text-fg">
        <input name="planApproval" type="checkbox" className="h-4 w-4 rounded border-line" />
        {t('planApproval')}
      </label>
      <input type="hidden" name="languages" value="ja,ko,en" />
      <input type="hidden" name="canonicalLanguage" value="ja" />
      <button type="submit" className={btnCls} disabled={pending}>
        {pending ? '…' : t('launch')}
      </button>
      {result && (
        <div className={`rounded-lg px-3 py-2 font-mono text-xs ${
          result.ok ? 'bg-emerald-500/10 text-emerald-300' : 'bg-red-500/10 text-red-300'}`}>
          {result.ok ? t('launched') : result.detail.slice(0, 300)}
        </div>
      )}
    </form>
  );
}
