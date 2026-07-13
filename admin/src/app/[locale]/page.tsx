import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { Icon } from '@/components/icons';
import {
  btnCls, Card, Chip, EmptyState, linkCls, PageHeader, StatCard, StatusBadge, Table, tdCls,
} from '@/components/ui';
import { runJobNow, saveAutomation } from '@/lib/actions';
import { FORMATS } from '@/lib/constants';
import type { Run } from '@/lib/types';
import {
  getCategories, getChannelHealth, getDrafts, getMonthCostUsd, getPromptTemplates,
  getRecentPosts, getRecentRuns,
} from '@/lib/data';

const fmt = (iso?: string) => (iso ? iso.slice(0, 16).replace('T', ' ') : null);

function StageStatus({
  label,
  run,
  okLabel,
  failedLabel,
  neverLabel,
}: {
  label: string;
  run?: Run;
  okLabel: string;
  failedLabel: string;
  neverLabel: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-1 rounded-lg border border-line bg-paper/60 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </div>
      {run ? (
        <>
          <div
            className={`inline-flex items-center gap-1.5 text-sm font-semibold ${
              run.ok ? 'text-emerald-700' : 'text-red-600'
            }`}
          >
            <span className={`h-2 w-2 rounded-full ${run.ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
            {run.ok ? okLabel : failedLabel}
          </div>
          <div className="font-mono text-xs text-slate-400">{fmt(run.startedAt)}</div>
        </>
      ) : (
        <div className="text-sm text-slate-400">{neverLabel}</div>
      )}
    </div>
  );
}

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

  const lastCollect = runs.find((r) => r.jobType === 'collect');
  const lastGenerate = runs.find((r) => r.jobType.startsWith('generate'));
  const latestPost = posts[0];

  const expiresAt = health.threadsTokenExpiresAt
    ? new Date(health.threadsTokenExpiresAt)
    : null;
  const daysLeft = expiresAt
    ? Math.floor((expiresAt.getTime() - Date.now()) / 86_400_000)
    : null;
  const tokenDanger =
    !!health.threadsRefreshError || (daysLeft !== null && daysLeft < 14);

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} />

      {health.threadsRefreshError && (
        <div className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
          <span>
            {t('refreshError')}: {health.threadsRefreshError}
          </span>
        </div>
      )}

      <Card title={t('flowTitle')}>
        <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
          <StageStatus
            label={`① ${t('stageCollect')}`}
            run={lastCollect}
            okLabel={t('runOk')}
            failedLabel={t('runFailed')}
            neverLabel={t('neverRan')}
          />
          <Icon
            name="arrowRight"
            size={16}
            className="mx-auto shrink-0 rotate-90 text-slate-300 sm:mx-0 sm:rotate-0"
          />
          <StageStatus
            label={`② ${t('stageGenerate')}`}
            run={lastGenerate}
            okLabel={t('runOk')}
            failedLabel={t('runFailed')}
            neverLabel={t('neverRan')}
          />
          <Icon
            name="arrowRight"
            size={16}
            className="mx-auto shrink-0 rotate-90 text-slate-300 sm:mx-0 sm:rotate-0"
          />
          <div className="flex min-w-0 flex-1 flex-col gap-1 rounded-lg border border-line bg-paper/60 px-4 py-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              ③ {t('stagePublish')}
            </div>
            {latestPost ? (
              <>
                <div>
                  <StatusBadge status={latestPost.status} />
                </div>
                <div className="truncate font-mono text-xs text-slate-400">
                  {fmt(latestPost.createdAt)} · {latestPost.title || latestPost.id}
                </div>
              </>
            ) : (
              <div className="text-sm text-slate-400">{t('noPosts')}</div>
            )}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard label={t('monthCost')} value={`$${monthCost.toFixed(2)}`} />
        <StatCard
          label={t('threadsToken')}
          danger={tokenDanger}
          value={daysLeft !== null ? t('daysLeft', { days: daysLeft }) : '—'}
          sub={expiresAt ? `${t('expiresAt')}: ${expiresAt.toISOString().slice(0, 10)}` : undefined}
        />
        <StatCard
          label={t('pendingDrafts')}
          value={drafts.length}
          footer={
            <Link href={`/${locale}/drafts`} className={linkCls}>
              {t('viewAll')} →
            </Link>
          }
        />
      </div>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <Card title={t('automation')} hint={t('automationHint')}>
            <form action={saveAutomation}>
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    <th className="pb-2"></th>
                    {FORMATS.map((fmt) => (
                      <th
                        key={fmt}
                        className="pb-2 pr-3 text-left font-mono text-[11px] font-medium uppercase tracking-wider text-slate-400"
                      >
                        {fmt}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {categories.map((cat) => (
                    <tr key={cat.slug} className="border-t border-line/60">
                      <td className="py-2.5 pr-3 text-[13px] font-medium text-ink">{cat.name}</td>
                      {FORMATS.map((fmt) => {
                        const id = `${cat.slug}_${fmt}`;
                        const tpl = templateById.get(id);
                        return (
                          <td key={fmt} className="py-2.5 pr-3">
                            {tpl ? (
                              <label className="inline-flex items-center gap-1.5">
                                <input type="hidden" name="ids" value={id} />
                                <input
                                  type="checkbox"
                                  name={`enabled_${id}`}
                                  defaultChecked={tpl.enabled}
                                  className="h-4 w-4 rounded border-line"
                                />
                              </label>
                            ) : (
                              <Link
                                href={`/${locale}/prompts/${id}`}
                                className="text-xs text-slate-400 underline underline-offset-2 hover:text-accent"
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
              <div className="mt-4">
                <button type="submit" className={btnCls}>{tc('save')}</button>
              </div>
            </form>
          </Card>
        </div>

        <div className="xl:col-span-2">
          <Card title={t('generate')} hint={t('generateHint')}>
            <div className="flex flex-wrap gap-2.5">
              <ActionButton action={runJobNow.bind(null, 'collect')} label={t('collect')} secondary />
              <ActionButton action={runJobNow.bind(null, 'generate_short')} label={t('short')} />
              <ActionButton action={runJobNow.bind(null, 'generate_article')} label={t('article')} />
            </div>
          </Card>
        </div>
      </div>

      <Card title={t('pendingDrafts')} flush>
        {drafts.length === 0 ? (
          <EmptyState message={t('noDrafts')} />
        ) : (
          <ul className="divide-y divide-line/60">
            {drafts.slice(0, 5).map((d) => (
              <li key={d.id} className="flex items-center gap-3 px-5 py-3 text-sm">
                <Chip>{d.format}</Chip>
                <Link href={`/${locale}/drafts/${d.id}`} className={`${linkCls} min-w-0 truncate`}>
                  {d.title || d.id}
                </Link>
                <span className="ml-auto shrink-0 font-mono text-xs text-slate-400">
                  {d.categoryId}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t('recentPosts')} flush>
        {posts.length === 0 ? (
          <EmptyState message={t('noPosts')} />
        ) : (
          <Table>
            <tbody>
              {posts.map((p) => (
                <tr key={p.id}>
                  <td className={`${tdCls} w-36`}>
                    <StatusBadge status={p.status} />
                  </td>
                  <td className={`${tdCls} max-w-64`}>
                    <div className="truncate text-[13px] font-medium text-ink">
                      {p.title || p.id}
                    </div>
                    <div className="mt-0.5 font-mono text-[11px] text-slate-400">
                      {p.format} / {p.categoryId}
                    </div>
                  </td>
                  <td className={tdCls}>
                    <div className="flex flex-wrap gap-x-3 gap-y-1">
                      {Object.entries(p.channels).map(([name, ch]) => (
                        <span key={name} className="inline-flex items-center gap-1.5 text-xs">
                          <span className="font-mono text-slate-500">{name}</span>
                          <StatusBadge status={ch.status} />
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card title={t('recentRuns')} flush>
        <Table>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td className={`${tdCls} w-44 font-mono text-xs text-ink`}>{r.jobType}</td>
                <td className={`${tdCls} w-28`}>
                  <span
                    className={`inline-flex items-center gap-1.5 font-mono text-xs font-medium ${
                      r.ok ? 'text-emerald-700' : 'text-red-600'
                    }`}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${r.ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
                    {r.ok ? t('runOk') : t('runFailed')}
                  </span>
                </td>
                <td className={`${tdCls} w-40 font-mono text-xs text-slate-400`}>
                  {fmt(r.startedAt)}
                </td>
                <td className={`${tdCls} text-xs text-slate-500`}>
                  <span className="font-mono">{r.stats ? JSON.stringify(r.stats) : ''}</span>
                  {r.errors && r.errors.length > 0 && (
                    <span className="text-red-600"> {r.errors[0]?.slice(0, 80)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
