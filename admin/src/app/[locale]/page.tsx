import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { Card, StatusBadge } from '@/components/ui';
import {
  getChannelHealth, getDrafts, getMonthCostUsd, getRecentPosts, getRecentRuns,
} from '@/lib/data';

export default async function Dashboard({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations('dashboard');
  const [drafts, posts, runs, monthCost, health] = await Promise.all([
    getDrafts(),
    getRecentPosts(10),
    getRecentRuns(10),
    getMonthCostUsd(),
    getChannelHealth(),
  ]);

  const expiresAt = health.threadsTokenExpiresAt
    ? new Date(health.threadsTokenExpiresAt)
    : null;
  const daysLeft = expiresAt
    ? Math.floor((expiresAt.getTime() - Date.now()) / 86_400_000)
    : null;
  const tokenDanger =
    !!health.threadsRefreshError || (daysLeft !== null && daysLeft < 14);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t('title')}</h1>

      {health.threadsRefreshError && (
        <div className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          {t('refreshError')}: {health.threadsRefreshError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card title={t('monthCost')}>
          <div className="text-2xl font-bold">${monthCost.toFixed(2)}</div>
        </Card>
        <Card title={t('threadsToken')}>
          {expiresAt ? (
            <div className={tokenDanger ? 'text-red-700' : ''}>
              <div className="text-2xl font-bold">
                {daysLeft !== null ? t('daysLeft', { days: daysLeft }) : '—'}
              </div>
              <div className="text-xs text-slate-500">
                {t('expiresAt')}: {expiresAt.toISOString().slice(0, 10)}
              </div>
            </div>
          ) : (
            <div className="text-slate-400">—</div>
          )}
        </Card>
        <Card title={t('pendingDrafts')}>
          <div className="text-2xl font-bold">{drafts.length}</div>
          <Link href={`/${locale}/drafts`} className="text-xs text-sky-700 underline">
            {t('viewAll')}
          </Link>
        </Card>
      </div>

      <Card title={t('pendingDrafts')}>
        {drafts.length === 0 ? (
          <div className="text-sm text-slate-400">{t('noDrafts')}</div>
        ) : (
          <ul className="space-y-1">
            {drafts.slice(0, 5).map((d) => (
              <li key={d.id} className="flex items-center gap-2 text-sm">
                <StatusBadge status={d.cadence} />
                <Link
                  href={`/${locale}/drafts/${d.id}`}
                  className="text-sky-700 underline"
                >
                  {d.title || d.id}
                </Link>
                <span className="text-xs text-slate-400">{d.categoryId}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t('recentPosts')}>
        <table className="w-full text-sm">
          <tbody>
            {posts.map((p) => (
              <tr key={p.id} className="border-t border-slate-100">
                <td className="py-1.5 pr-2">
                  <StatusBadge status={p.status} />
                </td>
                <td className="py-1.5 pr-2">{p.title || p.id}</td>
                <td className="py-1.5 pr-2 text-xs text-slate-400">
                  {p.cadence} / {p.categoryId}
                </td>
                <td className="py-1.5">
                  <div className="flex gap-1">
                    {Object.entries(p.channels).map(([name, ch]) => (
                      <span key={name} className="text-xs">
                        {name}: <StatusBadge status={ch.status} />
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title={t('recentRuns')}>
        <table className="w-full text-sm">
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className="border-t border-slate-100">
                <td className="py-1.5 pr-2 font-mono text-xs">{r.jobType}</td>
                <td className="py-1.5 pr-2">
                  <StatusBadge status={r.ok ? 'published' : 'failed'} />
                </td>
                <td className="py-1.5 pr-2 text-xs text-slate-400">
                  {r.startedAt.slice(0, 16).replace('T', ' ')}
                </td>
                <td className="py-1.5 text-xs text-slate-500">
                  {r.stats ? JSON.stringify(r.stats) : ''}
                  {r.errors && r.errors.length > 0 && (
                    <span className="text-red-600"> {r.errors[0]?.slice(0, 80)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
