import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { Card, StatusBadge } from '@/components/ui';
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
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t('title')}</h1>
      <Card>
        {drafts.length === 0 ? (
          <div className="text-sm text-slate-400">{t('empty')}</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-1">{tc('cadence')}</th>
                <th>{tc('title')}</th>
                <th>{tc('category')}</th>
                <th>{tc('created')}</th>
              </tr>
            </thead>
            <tbody>
              {drafts.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="py-2"><StatusBadge status={d.cadence} /></td>
                  <td>
                    <Link href={`/${locale}/drafts/${d.id}`} className="text-sky-700 underline">
                      {d.title || d.id}
                    </Link>
                  </td>
                  <td className="text-xs text-slate-500">{d.categoryId}</td>
                  <td className="text-xs text-slate-400">
                    {d.createdAt.slice(0, 16).replace('T', ' ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
