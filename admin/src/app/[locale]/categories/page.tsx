import { getTranslations } from 'next-intl/server';
import { Card, StatusBadge, btnCls, inputCls } from '@/components/ui';
import { getCategories } from '@/lib/data';
import { saveCategory } from '@/lib/actions';

export default async function CategoriesPage() {
  const [t, tc, categories] = await Promise.all([
    getTranslations('categories'),
    getTranslations('common'),
    getCategories(),
  ]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t('title')}</h1>

      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th className="py-1">{t('slug')}</th>
              <th>{t('name')}</th>
              <th>{t('searchHints')}</th>
              <th>{tc('status')}</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => (
              <tr key={c.slug} className="border-t border-slate-100">
                <td className="py-2 font-mono text-xs">{c.slug}</td>
                <td>{c.name}</td>
                <td className="text-xs text-slate-500">{c.searchHints?.join(', ')}</td>
                <td>
                  <StatusBadge status={c.enabled ? 'published' : 'skipped'} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title={t('addTitle')}>
        <form action={saveCategory} className="grid max-w-xl grid-cols-2 gap-3">
          <label className="text-sm">
            {t('slug')}
            <input name="slug" required className={inputCls} placeholder="business-economics" />
          </label>
          <label className="text-sm">
            {t('name')}
            <input name="name" required className={inputCls} />
          </label>
          <label className="col-span-2 text-sm">
            {t('searchHints')}
            <input name="searchHints" className={inputCls} />
          </label>
          <label className="text-sm">
            {t('sortOrder')}
            <input name="sortOrder" type="number" defaultValue={0} className={inputCls} />
          </label>
          <label className="flex items-end gap-2 pb-2 text-sm">
            <input name="enabled" type="checkbox" defaultChecked /> {tc('enabled')}
          </label>
          <div className="col-span-2">
            <button type="submit" className={btnCls}>{tc('save')}</button>
          </div>
        </form>
      </Card>
    </div>
  );
}
