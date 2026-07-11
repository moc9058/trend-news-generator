import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { Card, StatusBadge, btnCls, inputCls } from '@/components/ui';
import { SOURCE_TYPES } from '@/lib/constants';
import { deleteSource, runJobNow, saveSource, toggleSource } from '@/lib/actions';
import { getCategories, getSources } from '@/lib/data';

export default async function SourcesPage() {
  const [t, tc, sources, categories] = await Promise.all([
    getTranslations('sources'),
    getTranslations('common'),
    getSources(),
    getCategories(),
  ]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">{t('title')}</h1>
        <ActionButton action={runJobNow.bind(null, 'collect')} label={t('runCollect')} secondary />
      </div>
      <p className="text-xs text-slate-500">{t('collectHint')}</p>

      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th className="py-1">ID</th>
              <th>{tc('category')}</th>
              <th>{t('type')}</th>
              <th>{t('urlOrQuery')}</th>
              <th>{t('lastFetched')}</th>
              <th>{tc('status')}</th>
              <th>{tc('actions')}</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id} className="border-t border-slate-100">
                <td className="py-2 font-mono text-xs">{s.id}</td>
                <td className="text-xs">{s.categoryId}</td>
                <td className="font-mono text-xs">{s.type}</td>
                <td className="max-w-md truncate text-xs text-slate-500">{s.url || s.query}</td>
                <td className="text-xs text-slate-400">{s.lastFetchedAt?.slice(0, 16)}</td>
                <td><StatusBadge status={s.enabled ? 'published' : 'skipped'} /></td>
                <td className="space-x-1 whitespace-nowrap">
                  <form action={toggleSource.bind(null, s.id, !s.enabled)} className="inline">
                    <button className="text-xs text-sky-700 underline">
                      {s.enabled ? tc('disabled') : tc('enabled')}
                    </button>
                  </form>
                  <form action={deleteSource.bind(null, s.id)} className="inline">
                    <button className="text-xs text-red-600 underline">{tc('delete')}</button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title={t('addTitle')}>
        <form action={saveSource} className="grid max-w-xl grid-cols-2 gap-3">
          <label className="text-sm">
            {t('id')}
            <input name="id" className={inputCls} />
          </label>
          <label className="text-sm">
            {tc('category')}
            <select name="categoryId" className={inputCls}>
              {categories.map((c) => (
                <option key={c.slug} value={c.slug}>{c.name}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            {t('type')}
            <select name="type" className={inputCls}>
              {SOURCE_TYPES.map((st) => (
                <option key={st} value={st}>{st}</option>
              ))}
            </select>
          </label>
          <label className="flex items-end gap-2 pb-2 text-sm">
            <input name="enabled" type="checkbox" defaultChecked /> {tc('enabled')}
          </label>
          <label className="col-span-2 text-sm">
            {t('url')}
            <input name="url" className={inputCls} placeholder="https://example.com/feed.xml" />
          </label>
          <label className="col-span-2 text-sm">
            {t('query')}
            <input name="query" className={inputCls} />
          </label>
          <div className="col-span-2">
            <button type="submit" className={btnCls}>{tc('save')}</button>
          </div>
        </form>
      </Card>
    </div>
  );
}
