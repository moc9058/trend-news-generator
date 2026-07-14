import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { Icon } from '@/components/icons';
import {
  btnCls, Card, Chip, EmptyState, linkCls, PageHeader, StatCard, StatusBadge, Table, tdCls,
} from '@/components/ui';
import { runJobNow, runReportNow, saveAutomation } from '@/lib/actions';
import { CHANNELS, FORMATS } from '@/lib/constants';
import {
  getAppSettings, getCategories, getChannelConfigs, getChannelHealth, getCostSummary,
  getDrafts, getPromptTemplates, getRecentPosts,
} from '@/lib/data';

const fmtDate = (iso?: string) => (iso ? iso.slice(0, 16).replace('T', ' ') : null);

const CHANNEL_SHORT: Record<string, string> = { x: 'X', threads: 'Threads', notion: 'Notion' };

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
  const [drafts, posts, cost, health, categories, templates, channelConfigs, settings] =
    await Promise.all([
      getDrafts(),
      getRecentPosts(8),
      getCostSummary(),
      getChannelHealth(),
      getCategories(),
      getPromptTemplates(),
      getChannelConfigs(),
      getAppSettings(),
    ]);
  const templateById = new Map(templates.map((tpl) => [tpl.id, tpl]));
  const configById = new Map(channelConfigs.map((cfg) => [cfg.id, cfg]));
  // Only channels switched on globally (settings page) appear in the grid.
  const visibleChannels = CHANNELS.filter((ch) => settings.globalChannels[ch]);

  const scheduleLabel: Record<string, string> = {
    short: t('scheduleShort'),
    article: t('scheduleArticle'),
    report: t('scheduleReport'),
  };

  const expiresAt = health.threadsTokenExpiresAt ? new Date(health.threadsTokenExpiresAt) : null;
  const daysLeft = expiresAt
    ? Math.floor((expiresAt.getTime() - Date.now()) / 86_400_000)
    : null;
  const tokenDanger = !!health.threadsRefreshError || (daysLeft !== null && daysLeft < 14);

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} hint={t('hint')} />

      {health.threadsRefreshError && (
        <div className="flex items-start gap-2.5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
          <span>
            {t('refreshError')}: {health.threadsRefreshError}
          </span>
        </div>
      )}

      {/* ② LLM cost */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard label={t('monthCost')} value={`$${cost.monthUsd.toFixed(2)}`} />
        <StatCard label={t('totalCost')} value={`$${cost.totalUsd.toFixed(2)}`} />
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

      {/* ① automation: per category x format, with schedule + channel toggles */}
      <Card title={t('automation')} hint={t('automationHint')}>
        <form action={saveAutomation}>
          {visibleChannels.map((ch) => (
            <input key={ch} type="hidden" name="channels" value={ch} />
          ))}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr>
                  <th className="pb-3"></th>
                  {FORMATS.map((fmt) => (
                    <th key={fmt} className="pb-3 pr-4 text-left align-top">
                      <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-ink">
                        {fmt}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1 text-[11px] font-normal normal-case text-slate-400">
                        <Icon name="clock" size={11} className="shrink-0" />
                        {scheduleLabel[fmt]}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {categories.map((cat) => (
                  <tr key={cat.slug} className="border-t border-line/60">
                    <td className="py-3 pr-3 align-top text-[13px] font-medium text-ink">
                      {cat.name}
                    </td>
                    {FORMATS.map((fmt) => {
                      const id = `${cat.slug}_${fmt}`;
                      const tpl = templateById.get(id);
                      if (!tpl) {
                        return (
                          <td key={fmt} className="py-3 pr-4 align-top">
                            <Link
                              href={`/${locale}/prompts/${id}`}
                              className="text-xs text-slate-400 underline underline-offset-2 hover:text-accent"
                            >
                              {tp('notSeeded')}
                            </Link>
                          </td>
                        );
                      }
                      return (
                        <td key={fmt} className="py-3 pr-4 align-top">
                          <input type="hidden" name="ids" value={id} />
                          <div className="space-y-1.5">
                            <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs font-medium text-slate-600">
                              <input
                                type="checkbox"
                                name={`enabled_${id}`}
                                defaultChecked={tpl.enabled}
                                className="h-4 w-4 rounded border-line"
                              />
                              {t('generateOn')}
                            </label>
                            <div className="flex flex-wrap gap-1">
                              {visibleChannels.map((ch) => {
                                const cfg = configById.get(`${id}_${ch}`);
                                return (
                                  <label
                                    key={ch}
                                    className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-line bg-paper/60 px-1.5 py-0.5 text-[11px] text-slate-500 has-[:checked]:border-accent-line has-[:checked]:bg-accent-soft has-[:checked]:text-accent"
                                  >
                                    <input
                                      type="checkbox"
                                      name={`ch_${id}_${ch}`}
                                      defaultChecked={cfg?.enabled ?? false}
                                      className="h-3 w-3 rounded border-line"
                                    />
                                    {CHANNEL_SHORT[ch]}
                                  </label>
                                );
                              })}
                            </div>
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button type="submit" className={btnCls}>{tc('save')}</button>
            <span className="text-xs text-slate-400">{t('channelToggleHint')}</span>
          </div>
        </form>
      </Card>

      {/* ③ manual run */}
      <Card title={t('generate')} hint={t('generateHint')}>
        <div className="flex flex-wrap gap-2.5">
          <ActionButton action={runJobNow.bind(null, 'generate_short')} label={t('short')} />
          <ActionButton action={runJobNow.bind(null, 'generate_article')} label={t('article')} />
          <ActionButton action={runReportNow} label={t('report')} />
        </div>
      </Card>

      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <Card title={t('pendingDrafts')} flush>
          {drafts.length === 0 ? (
            <EmptyState message={t('noDrafts')} />
          ) : (
            <ul className="divide-y divide-line/60">
              {drafts.slice(0, 6).map((d) => (
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

        <Card
          title={t('recentPosts')}
          flush
          actions={
            <Link href={`/${locale}/posts`} className={`${linkCls} text-xs`}>
              {t('viewAll')} →
            </Link>
          }
        >
          {posts.length === 0 ? (
            <EmptyState message={t('noPosts')} />
          ) : (
            <Table>
              <tbody>
                {posts.map((p) => (
                  <tr key={p.id}>
                    <td className={`${tdCls} w-32`}>
                      <StatusBadge status={p.status} />
                    </td>
                    <td className={`${tdCls} max-w-64`}>
                      <Link
                        href={`/${locale}/posts/${p.id}`}
                        className="block truncate text-[13px] font-medium text-ink underline-offset-2 hover:text-accent hover:underline"
                      >
                        {p.title || p.id}
                      </Link>
                      <div className="mt-0.5 font-mono text-[11px] text-slate-400">
                        {p.format} / {p.categoryId} / {fmtDate(p.createdAt)}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
    </div>
  );
}
