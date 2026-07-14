import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { Card, Chip, EmptyState, PageHeader, StatusBadge, Table, tdCls, thCls } from '@/components/ui';
import { ResearchLauncher } from '@/components/ResearchLauncher';
import { getCategories, getResearchRuns } from '@/lib/data';

export default async function ResearchPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, runs, categories] = await Promise.all([
    getTranslations('research'),
    getResearchRuns(),
    getCategories(),
  ]);

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} hint={t('hint')} />
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-3">
        <div className="xl:col-span-1">
          <Card title={t('launch')} hint={t('launchHint')}>
            <ResearchLauncher categories={categories.map((c) => ({ slug: c.slug, name: c.name }))} />
          </Card>
        </div>
        <div className="xl:col-span-2">
          <Card title={t('runs')} flush>
            {runs.length === 0 ? (
              <EmptyState message={t('noRuns')} />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <th className={thCls}>{t('status')}</th>
                    <th className={thCls}>{t('theme')}</th>
                    <th className={thCls}>{t('phase')}</th>
                    <th className={thCls}>{t('cost')}</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id}>
                      <td className={tdCls}><StatusBadge status={r.status} /></td>
                      <td className={`${tdCls} max-w-md`}>
                        <Link href={`/${locale}/research/${r.id}`}
                          className="font-medium text-accent underline-offset-2 hover:underline">
                          {r.theme || r.id}
                        </Link>
                        <div className="mt-0.5 font-mono text-[11px] text-slate-400">{r.categoryId}</div>
                      </td>
                      <td className={tdCls}><Chip>{r.phase}</Chip></td>
                      <td className={`${tdCls} whitespace-nowrap font-mono text-xs text-slate-500`}>
                        ${(r.budget?.usdSpent ?? 0).toFixed(2)} / {(r.budget?.usdCap ?? 0).toFixed(0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
