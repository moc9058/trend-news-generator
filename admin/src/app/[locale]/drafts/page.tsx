import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { btnDangerCls, Card, Chip, EmptyState, linkCls, PageHeader, Table, tdCls, thCls } from '@/components/ui';
import { deleteDraft } from '@/lib/actions';
import { getDrafts } from '@/lib/data';

export default async function DraftsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, tc, drafts] = await Promise.all([
    getTranslations('drafts'),
    getTranslations('common'),
    getDrafts(),
  ]);

  return (
    <div>
      <PageHeader title={t('title')} hint={t('autoDeleteNote')} />
      <Card flush>
        {drafts.length === 0 ? (
          <EmptyState message={t('empty')} />
        ) : (
          <Table>
            <thead>
              <tr>
                <th className={thCls}>{tc('format')}</th>
                <th className={thCls}>{tc('title')}</th>
                <th className={thCls}>{tc('category')}</th>
                <th className={thCls}>{tc('created')}</th>
                <th className={thCls}>{tc('actions')}</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((d) => (
                <tr key={d.id} className="transition-colors hover:bg-paper/50">
                  <td className={tdCls}>
                    <Chip>{d.format}</Chip>
                  </td>
                  <td className={`${tdCls} max-w-md`}>
                    <Link href={`/${locale}/drafts/${d.id}`} className={`${linkCls} block truncate`}>
                      {d.title || d.id}
                    </Link>
                  </td>
                  <td className={`${tdCls} font-mono text-xs text-slate-500`}>{d.categoryId}</td>
                  <td className={`${tdCls} font-mono text-xs text-slate-400`}>
                    {d.createdAt.slice(0, 16).replace('T', ' ')}
                  </td>
                  <td className={tdCls}>
                    <form action={deleteDraft.bind(null, d.id)} className="inline">
                      <button className={btnDangerCls}>{tc('delete')}</button>
                    </form>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
