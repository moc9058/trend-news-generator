import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { btnCls, Card, StatusBadge } from '@/components/ui';
import { runJobNow, saveAutomation } from '@/lib/actions';
import { CADENCES } from '@/lib/constants';
import {
  getCategories, getChannelHealth, getDrafts, getMonthCostUsd, getPromptTemplates,
  getRecentPosts, getRecentRuns,
} from '@/lib/data';

export default async function Dashboard({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, tc, tp] = await Promise.all([
    getTranslations('dashboard'),
    getTranslations('common'),
    getTranslations('prompts'),
  ]);
  const [drafts, posts, runs, monthCost, health, categories, templates] = await Promise.all([
    getDrafts(),
    getRecentPosts(10),
    getRecentRuns(10),
    getMonthCostUsd(),
    getChannelHealth(),
    getCategories(),
    getPromptTemplates(),
  ]);
  const templateById = new Map(templates.map((tpl) => [tpl.id, tpl]));

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

      <Card title={t('automation')}>
        <p className="mb-3 text-xs text-slate-500">{t('automationHint')}</p>
        <form action={saveAutomation}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-1"></th>
                {CADENCES.map((cadence) => (
                  <th key={cadence} className="py-1 pr-3">{cadence}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {categories.map((cat) => (
                <tr key={cat.slug} className="border-t border-slate-100">
                  <td className="py-2 pr-3 text-xs font-medium">{cat.name}</td>
                  {CADENCES.map((cadence) => {
                    const id = `${cat.slug}_${cadence}`;
                    const tpl = templateById.get(id);
                    return (
                      <td key={cadence} className="py-2 pr-3">
                        {tpl ? (
                          <label className="inline-flex items-center gap-1.5">
                            <input type="hidden" name="ids" value={id} />
                            <input
                              type="checkbox"
                              name={`enabled_${id}`}
                              defaultChecked={tpl.enabled}
                              className="h-4 w-4 rounded border-slate-300"
                            />
                          </label>
                        ) : (
                          <Link
                            href={`/${locale}/prompts/${id}`}
                            className="text-xs text-slate-400 underline"
                          >
                            {tp('notSeeded')}
                          </Link>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-3">
            <button type="submit" className={btnCls}>{tc('save')}</button>
          </div>
        </form>
      </Card>

      <Card title={t('generate')}>
        <p className="mb-3 text-xs text-slate-500">{t('generateHint')}</p>
        <div className="flex flex-wrap gap-3">
          <ActionButton action={runJobNow.bind(null, 'collect')} label={t('collect')} secondary />
          <ActionButton action={runJobNow.bind(null, 'generate_daily')} label={t('daily')} />
          <ActionButton action={runJobNow.bind(null, 'generate_weekly')} label={t('weekly')} />
          <ActionButton action={runJobNow.bind(null, 'generate_monthly')} label={t('monthly')} />
        </div>
      </Card>

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
