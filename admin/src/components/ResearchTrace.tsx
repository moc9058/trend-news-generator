import { getTranslations } from 'next-intl/server';
import { Card, EmptyState } from './ui';
import { TraceTree } from './TraceTree';
import { getResearchTrace } from '@/lib/langsmith';

/* Server component behind a Suspense boundary in the run page: LangSmith is a
   third-party round trip and must not hold up the Firestore-backed sections. */
export async function ResearchTrace({ runId }: { runId: string }) {
  const [t, trace] = await Promise.all([getTranslations('research'), getResearchTrace(runId)]);
  if (!trace) {
    // Tracing off, run predates it, or LangSmith is unreachable — same handling.
    return null;
  }

  return (
    <Card
      title={t('trace')}
      hint={t('traceHint')}
      flush
      actions={
        trace.url ? (
          <a href={trace.url} target="_blank" rel="noreferrer"
            className="inline-flex items-center rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-accent shadow-card hover:bg-paper">
            {t('traceOpen')}
          </a>
        ) : undefined
      }
    >
      {trace.spans.length === 0
        ? <EmptyState message={t('noTrace')} />
        : <TraceTree spans={trace.spans} clipped={trace.clipped} />}
    </Card>
  );
}
