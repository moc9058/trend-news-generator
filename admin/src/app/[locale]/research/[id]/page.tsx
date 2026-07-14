import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { ResearchFlow } from '@/components/ResearchFlow';
import {
  Card, Chip, EmptyState, PageHeader, StatusBadge, Table, tdCls, thCls,
} from '@/components/ui';
import { approveResearchPlan, cancelResearchRun } from '@/lib/actions';
import {
  getResearchClaims, getResearchEvidence, getResearchEvents, getResearchRun,
} from '@/lib/data';

const TERMINAL = new Set(['awaiting_review', 'completed', 'failed', 'cancelled', 'budget_exhausted']);

export default async function ResearchRunPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  const [t, run] = await Promise.all([getTranslations('research'), getResearchRun(id)]);
  if (!run) notFound();

  const [evidence, claims, events] = await Promise.all([
    getResearchEvidence(id), getResearchClaims(id), getResearchEvents(id),
  ]);

  return (
    <div className="space-y-5">
      <PageHeader title={run.theme || run.id} hint={`${run.categoryId} · ${run.trigger}`}>
        <StatusBadge status={run.status} />
        {run.status === 'awaiting_plan_approval' && (
          <ActionButton action={approveResearchPlan.bind(null, run.id)} label={t('approvePlan')} />
        )}
        {!TERMINAL.has(run.status) && (
          <ActionButton action={cancelResearchRun.bind(null, run.id)} label={t('cancel')}
            confirmText={t('confirmCancel')} secondary />
        )}
        {run.postId && (
          <Link href={`/${locale}/drafts/${run.postId}`}
            className="inline-flex items-center rounded-lg border border-line bg-white px-3 py-2 text-sm font-medium text-accent shadow-card hover:bg-paper">
            {t('openDraft')}
          </Link>
        )}
      </PageHeader>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Meta label={t('phase')} value={run.phase} />
        <Meta label={t('loops')} value={String(run.loops)} />
        <Meta label={t('cost')} value={`$${(run.budget?.usdSpent ?? 0).toFixed(2)} / ${(run.budget?.usdCap ?? 0).toFixed(0)}`} />
        <Meta label={t('fetches')} value={`${run.budget?.fetchUsed ?? 0} / ${run.budget?.fetchCap ?? 0}`} />
      </div>

      <Card title={t('flow')} flush>
        <ResearchFlow run={run} events={events} />
      </Card>

      {run.plan && (
        <Card title={t('plan')} hint={run.plan.contested ? t('contested') : undefined}>
          <ul className="space-y-2">
            {run.plan.rqs.map((rq) => (
              <li key={rq.id} className="flex flex-wrap items-center gap-2 text-sm">
                <Chip>{rq.id}</Chip>
                <span className={rq.resolved ? 'text-ink' : 'text-slate-500'}>{rq.q}</span>
                <span className="ml-auto flex gap-1">
                  {rq.strategies.map((s) => <Chip key={s}>{s}</Chip>)}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title={`${t('evidence')} (${evidence.length})`} flush>
        {evidence.length === 0 ? <EmptyState message={t('noEvidence')} /> : (
          <Table>
            <thead><tr>
              <th className={thCls}>{t('tier')}</th>
              <th className={thCls}>{t('source')}</th>
              <th className={thCls}>{t('score')}</th>
            </tr></thead>
            <tbody>
              {evidence.map((e) => (
                <tr key={e.evidenceId}>
                  <td className={tdCls}><Chip>{e.tier}</Chip></td>
                  <td className={`${tdCls} max-w-lg`}>
                    <a href={e.url} target="_blank" rel="noreferrer"
                      className="font-medium text-accent underline-offset-2 hover:underline">
                      {e.title || e.url}
                    </a>
                    <div className="mt-0.5 font-mono text-[11px] text-slate-400">
                      {e.sourceType}{e.venue ? ` · ${e.venue}` : ''}{e.publishedAt ? ` · ${e.publishedAt}` : ''}
                    </div>
                  </td>
                  <td className={`${tdCls} font-mono text-xs`}>{e.reliability?.score ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card title={`${t('claims')} (${claims.length})`} flush>
        {claims.length === 0 ? <EmptyState message={t('noClaims')} /> : (
          <Table>
            <thead><tr>
              <th className={thCls}>{t('verdict')}</th>
              <th className={thCls}>{t('claim')}</th>
            </tr></thead>
            <tbody>
              {claims.map((c) => (
                <tr key={c.claimId}>
                  <td className={tdCls}>
                    <Chip>{c.renderAs || c.verdict}</Chip>
                    {c.stance && <div className="mt-1 font-mono text-[11px] text-slate-400">{c.stance}</div>}
                  </td>
                  <td className={`${tdCls} text-sm text-slate-700`}>{c.text}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Card title={t('timeline')} flush>
        {events.length === 0 ? <EmptyState message={t('noEvents')} /> : (
          <ul className="divide-y divide-line/60">
            {events.map((ev) => (
              <li key={ev.id} className="flex items-center gap-3 px-5 py-2 text-sm">
                <Chip>{ev.phase}</Chip>
                <span className="font-mono text-xs text-slate-500">{ev.actor}</span>
                <span className={ev.ok ? 'text-slate-600' : 'text-red-600'}>{ev.action}</span>
                {ev.model && <span className="font-mono text-[11px] text-slate-400">{ev.model}</span>}
                {ev.error && <span className="truncate text-xs text-red-500">{ev.error}</span>}
                <span className="ml-auto shrink-0 font-mono text-[11px] text-slate-400">
                  {ev.costUsd ? `$${ev.costUsd.toFixed(3)}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-white p-4 shadow-card">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className="mt-1 font-mono text-lg font-semibold text-ink">{value}</div>
    </div>
  );
}
