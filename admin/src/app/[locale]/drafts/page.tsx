import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { btnDangerCls, Card, Chip, EmptyState, linkCls, PageHeader, StatusBadge, Table, tdCls, thCls } from '@/components/ui';
import { AutoRefresh } from '@/components/AutoRefresh';
import { deleteDraft } from '@/lib/actions';
import { getDrafts, getInProgressResearchRuns } from '@/lib/data';

/** Runs still genuinely working (not the terminal failure states we also surface).
 * Only these keep the page polling. */
const LIVE_STATUSES = new Set(['queued', 'running', 'awaiting_plan_approval']);

export default async function DraftsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, tc, tr, drafts, inProgress] = await Promise.all([
    getTranslations('drafts'),
    getTranslations('common'),
    getTranslations('research'),
    getDrafts(),
    getInProgressResearchRuns(),
  ]);

  const polling = inProgress.some((r) => LIVE_STATUSES.has(r.status));

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} hint={t('autoDeleteNote')} />

      <AutoRefresh enabled={polling} />

      {inProgress.length > 0 && (
        <Card title={t('inProgress')} hint={t('inProgressHint')} flush>
          <Table>
            <thead>
              <tr>
                <th className={thCls}>{tr('status')}</th>
                <th className={thCls}>{tr('theme')}</th>
                <th className={thCls}>{tr('phase')}</th>
                <th className={thCls}>{tr('cost')}</th>
              </tr>
            </thead>
            <tbody>
              {inProgress.map((r) => (
                <tr key={r.id} className="transition-colors hover:bg-paper/50">
                  <td className={tdCls}><StatusBadge status={r.status} /></td>
                  <td className={`${tdCls} max-w-md`}>
                    <Link href={`/${locale}/research/${r.id}`}
                      className="font-medium text-accent underline-offset-2 hover:underline">
                      {r.theme || r.id}
                    </Link>
                    {r.status === 'awaiting_plan_approval' && (
                      <div className="mt-0.5 text-[11px] font-medium text-amber-300">
                        {t('planApprovalNeeded')}
                      </div>
                    )}
                    <div className="mt-0.5 font-mono text-[11px] text-fg-faint">{r.categoryId}</div>
                  </td>
                  <td className={tdCls}><Chip>{r.phase}</Chip></td>
                  <td className={`${tdCls} whitespace-nowrap font-mono text-xs text-fg-muted`}>
                    ${(r.budget?.usdSpent ?? 0).toFixed(2)} / {(r.budget?.usdCap ?? 0).toFixed(0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

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
                  <td className={`${tdCls} font-mono text-xs text-fg-muted`}>{d.categoryId}</td>
                  <td className={`${tdCls} font-mono text-xs text-fg-faint`}>
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
