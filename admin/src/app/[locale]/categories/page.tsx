import { getTranslations } from 'next-intl/server';
import { SaveForm } from '@/components/SaveForm';
import {
  Card, EnabledBadge, inputCls, labelCls, PageHeader, Table, tdCls, thCls,
} from '@/components/ui';
import { getCategories } from '@/lib/data';
import { saveCategory } from '@/lib/actions';

export default async function CategoriesPage() {
  const [t, tc, categories] = await Promise.all([
    getTranslations('categories'),
    getTranslations('common'),
    getCategories(),
  ]);

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} />

      <Card flush>
        <Table>
          <thead>
            <tr>
              <th className={thCls}>{t('slug')}</th>
              <th className={thCls}>{t('name')}</th>
              <th className={thCls}>{t('searchHints')}</th>
              <th className={thCls}>{tc('status')}</th>
            </tr>
          </thead>
          <tbody>
            {categories.map((c) => (
              <tr key={c.slug} className="transition-colors hover:bg-paper/50">
                <td className={`${tdCls} font-mono text-xs text-fg-muted`}>{c.slug}</td>
                <td className={`${tdCls} text-[13px] font-medium text-fg`}>{c.name}</td>
                <td className={`${tdCls} max-w-md text-xs text-fg-muted`}>
                  {c.searchHints?.join(', ')}
                </td>
                <td className={tdCls}>
                  <EnabledBadge enabled={c.enabled} labels={[tc('enabled'), tc('disabled')]} />
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <Card title={t('addTitle')}>
        <SaveForm
          action={saveCategory}
          saveLabel={tc('save')}
          savedLabel={tc('saved')}
          className="grid max-w-xl grid-cols-2 gap-4"
          footerClassName="col-span-2 mt-1 flex items-center gap-3"
        >
          <label className={labelCls}>
            {t('slug')}
            <input name="slug" required className={inputCls} placeholder="business-economics" />
          </label>
          <label className={labelCls}>
            {t('name')}
            <input name="name" required className={inputCls} />
          </label>
          <label className={`col-span-2 ${labelCls}`}>
            {t('searchHints')}
            <input name="searchHints" className={inputCls} />
          </label>
          <label className={labelCls}>
            {t('sortOrder')}
            <input name="sortOrder" type="number" defaultValue={0} className={inputCls} />
          </label>
          <label className="flex items-end gap-2 pb-2.5 text-sm text-fg-muted">
            <input name="enabled" type="checkbox" defaultChecked className="h-4 w-4 rounded border-line" />
            {tc('enabled')}
          </label>
        </SaveForm>
      </Card>
    </div>
  );
}
