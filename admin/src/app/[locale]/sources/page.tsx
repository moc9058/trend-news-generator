import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import {
  btnCls, btnDangerCls, Card, Chip, EnabledBadge, inputCls, labelCls, PageHeader, Table, tdCls, thCls,
} from '@/components/ui';
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
    <div className="space-y-5">
      <PageHeader title={t('title')} hint={t('collectHint')}>
        <ActionButton action={runJobNow.bind(null, 'collect')} label={t('runCollect')} secondary />
      </PageHeader>

      <Card flush>
        <Table>
          <thead>
            <tr>
              <th className={thCls}>ID</th>
              <th className={thCls}>{tc('category')}</th>
              <th className={thCls}>{t('type')}</th>
              <th className={thCls}>{t('urlOrQuery')}</th>
              <th className={thCls}>{t('lastFetched')}</th>
              <th className={thCls}>{tc('status')}</th>
              <th className={thCls}>{tc('actions')}</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id} className="transition-colors hover:bg-paper/50">
                <td className={`${tdCls} font-mono text-xs text-slate-600`}>{s.id}</td>
                <td className={`${tdCls} font-mono text-xs text-slate-500`}>{s.categoryId}</td>
                <td className={tdCls}>
                  <Chip>{s.type}</Chip>
                </td>
                <td className={`${tdCls} max-w-md truncate text-xs text-slate-500`}>
                  {s.url || s.query}
                </td>
                <td className={`${tdCls} font-mono text-xs text-slate-400`}>
                  {s.lastFetchedAt?.slice(0, 16).replace('T', ' ')}
                </td>
                <td className={tdCls}>
                  <EnabledBadge enabled={s.enabled} labels={[tc('enabled'), tc('disabled')]} />
                </td>
                <td className={`${tdCls} whitespace-nowrap`}>
                  <form action={toggleSource.bind(null, s.id, !s.enabled)} className="inline">
                    <button className="rounded-md px-2 py-1 text-xs font-medium text-accent transition-colors hover:bg-accent-soft">
                      {s.enabled ? tc('disabled') : tc('enabled')}
                    </button>
                  </form>
                  <form action={deleteSource.bind(null, s.id)} className="inline">
                    <button className={btnDangerCls}>{tc('delete')}</button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card title={t('addTitle')}>
        <form action={saveSource} className="grid max-w-xl grid-cols-2 gap-4">
          <label className={labelCls}>
            {t('id')}
            <input name="id" className={inputCls} />
          </label>
          <label className={labelCls}>
            {tc('category')}
            <select name="categoryId" className={inputCls}>
              {categories.map((c) => (
                <option key={c.slug} value={c.slug}>{c.name}</option>
              ))}
            </select>
          </label>
          <label className={labelCls}>
            {t('type')}
            <select name="type" className={inputCls}>
              {SOURCE_TYPES.map((st) => (
                <option key={st} value={st}>{st}</option>
              ))}
            </select>
          </label>
          <label className="flex items-end gap-2 pb-2.5 text-sm text-slate-600">
            <input name="enabled" type="checkbox" defaultChecked className="h-4 w-4 rounded border-line" />
            {tc('enabled')}
          </label>
          <label className={`col-span-2 ${labelCls}`}>
            {t('url')}
            <input name="url" className={inputCls} placeholder="https://example.com/feed.xml" />
          </label>
          <label className={`col-span-2 ${labelCls}`}>
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
