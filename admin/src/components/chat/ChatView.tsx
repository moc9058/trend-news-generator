'use client';

/** The chat surface, shared by the dashboard panel (`compact`) and /chat/[id].
 *
 * A research answer is NOT a chat bubble. It is a record: a head strip (kind,
 * trust band, cost), the prose, then the numbered apparatus. Sparring stays a
 * plain conversational block with neither band nor sources. The product's
 * central distinction — is this just talk, or is it backed by sources it
 * actually read? — is therefore structural, readable before a word is.
 *
 * The order (evidence, then prose) follows the data: the SSE contract emits
 * `sources` before the first `token`, so the band is populated by the time the
 * answer starts writing and nothing reflows.
 *
 * Messages already persisted arrive as `initialMessages` from a server
 * component; the in-flight answer lives in `useChatStream` until it lands.
 */

import { useEffect, useRef, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { Markdown } from '@/components/Markdown';
import { EmptyState } from '@/components/ui';
import { cancelChat } from '@/lib/actions';
import type { Category, ChatMessage, ChatSource } from '@/lib/types';
import { Apparatus } from './Apparatus';
import { Composer, type ComposerLabels } from './Composer';
import { HandoffMenu, type HandoffLabels } from './HandoffMenu';
import { TrustBand } from './TrustBand';
import { useChatStream } from './useChatStream';

export interface ChatLabels extends ComposerLabels, HandoffLabels {
  sources: string;
  empty: string;
  error: string;
  streaming: string;
  cancelled: string;
  costLabel: string;
  statusPlanning: string;
  statusSearching: string;
  statusSelecting: string;
  statusReading: string;
  statusGapCheck: string;
  statusSynthesizing: string;
}

const STAGE_KEY = {
  planning: 'statusPlanning',
  searching: 'statusSearching',
  selecting: 'statusSelecting',
  reading: 'statusReading',
  gap_check: 'statusGapCheck',
  synthesizing: 'statusSynthesizing',
} as const;

/** What the user said. Quiet and set back — the question is context for the
 * answer, not a competing object. */
function Turn({ children }: { children: React.ReactNode }) {
  return (
    <p className="whitespace-pre-wrap border-l-2 border-line py-1 pl-3 text-sm text-slate-500">
      {children}
    </p>
  );
}

function Kind({ mode, depth, labels }: { mode: string; depth?: string | null; labels: ChatLabels }) {
  return (
    <span className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.1em] text-accent">
      {mode === 'research' ? labels.modeResearch : labels.modeChat}
      {mode === 'research' && depth
        ? ` · ${depth === 'deep' ? labels.depthDeep : labels.depthQuick}`
        : ''}
    </span>
  );
}

/** A research answer. */
function Record({
  mode, depth, labels, sources, pendingCount, costUsd, children, footer, status,
}: {
  mode: string;
  depth?: string | null;
  labels: ChatLabels;
  sources: ChatSource[];
  pendingCount?: number;
  costUsd?: number | null;
  children: React.ReactNode;
  footer?: React.ReactNode;
  status?: React.ReactNode;
}) {
  const [litN, setLitN] = useState<number | null>(null);
  return (
    <article className="min-w-0 rounded-2xl border border-line bg-white px-4 py-3 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line pb-2.5">
        <div className="flex flex-col gap-1.5">
          <Kind mode={mode} depth={depth} labels={labels} />
          <TrustBand
            sources={sources}
            pendingCount={pendingCount}
            litN={litN}
            onLit={setLitN}
            label={labels.sources}
          />
        </div>
        <div className="flex items-center gap-3">
          {status}
          {typeof costUsd === 'number' && (
            <span className="font-mono text-[10.5px] tabular-nums text-slate-400">
              ${costUsd.toFixed(3)}
            </span>
          )}
        </div>
      </div>
      <div className="pt-3 text-sm leading-[1.9] text-ink">
        <MarkdownWithCites litN={litN} onLit={setLitN}>
          {children}
        </MarkdownWithCites>
      </div>
      <Apparatus sources={sources} litN={litN} onLit={setLitN} />
      {footer}
    </article>
  );
}

/** Bridges the cite handlers into Markdown only when the child is a string. */
function MarkdownWithCites({
  children, litN, onLit,
}: {
  children: React.ReactNode;
  litN: number | null;
  onLit: (n: number | null) => void;
}) {
  if (typeof children !== 'string') return <>{children}</>;
  return <Markdown cite={{ litN, onLit }}>{children}</Markdown>;
}

/** A sparring answer: only talk. No band, no sources, no cost strip — the
 * absence is the information. */
function Talk({ labels, children, footer }: {
  labels: ChatLabels;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-white px-4 py-3 shadow-card">
      <span className="mb-1.5 block font-mono text-[10.5px] uppercase tracking-[0.12em] text-slate-400">
        {labels.modeChat}
      </span>
      <div className="text-sm leading-[1.9] text-ink">{children}</div>
      {footer}
    </div>
  );
}

export function ChatView({
  threadId, initialMessages, labels, categories, compact, locale,
}: {
  threadId?: string;
  initialMessages: ChatMessage[];
  labels: ChatLabels;
  categories: Category[];
  compact?: boolean;
  locale: string;
}) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [currentThread, setCurrentThread] = useState(threadId ?? '');
  const { state, send, detach } = useChatStream();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Locally-echoed user turns, so the question appears the instant it is sent
  // rather than after the server round-trip.
  const [pending, setPending] = useState<{ content: string; mode: string; depth: string } | null>(
    null,
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [state.answer, state.progress, pending]);

  // A finished answer is authoritative in Firestore; re-render from the server.
  const settled = !state.streaming && !!state.answer && !state.error;
  useEffect(() => {
    if (!settled) return;
    const id = setTimeout(() => {
      setPending(null);
      startTransition(() => router.refresh());
    }, 400);
    return () => clearTimeout(id);
  }, [settled, router]);

  const onSend = (args: { content: string; mode: string; depth: string }) => {
    setPending(args);
    void send({ ...args, threadId: currentThread || undefined }).then(() => undefined);
  };

  // A brand-new thread gets its id from the `meta` event; adopt it so the next
  // message continues the same conversation (and the URL matches).
  useEffect(() => {
    if (!state.threadId || state.threadId === currentThread) return;
    setCurrentThread(state.threadId);
    if (!compact) router.replace(`/${locale}/chat/${state.threadId}`);
  }, [state.threadId, currentThread, compact, locale, router]);

  const stageLabel = state.progress ? labels[STAGE_KEY[state.progress.stage]] : '';
  const showEmpty = !initialMessages.length && !pending && !state.answer;
  const liveResearch = pending?.mode === 'research';

  const liveStatus = state.progress ? (
    <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-slate-500">
      <span className="h-2 w-2 animate-spin rounded-full border-2 border-accent border-t-transparent" />
      {stageLabel}
    </span>
  ) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className={`min-h-0 flex-1 space-y-4 overflow-y-auto ${compact ? 'max-h-80' : 'pr-1'}`}>
        {showEmpty && <EmptyState message={labels.empty} />}

        {initialMessages.map((m) => {
          if (m.role === 'user') return <Turn key={m.id}>{m.content}</Turn>;

          const footer =
            m.status === 'complete' && m.content ? (
              <HandoffMenu
                threadId={currentThread}
                messageId={m.id}
                categories={categories}
                labels={labels}
                locale={locale}
                handoffs={m.handoffs ?? []}
              />
            ) : null;

          if (m.status === 'error') {
            return (
              <div
                key={m.id}
                className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              >
                {labels.error}: {m.error}
              </div>
            );
          }

          const cancelled =
            m.status === 'cancelled' ? (
              <p className="mt-1.5 font-mono text-[10.5px] text-slate-400">{labels.cancelled}</p>
            ) : null;

          return m.mode === 'research' ? (
            <Record
              key={m.id}
              mode={m.mode}
              depth={m.depth}
              labels={labels}
              sources={m.sources ?? []}
              costUsd={m.usage?.costUsd ?? null}
              footer={
                <>
                  {cancelled}
                  {footer}
                </>
              }
            >
              {m.content}
            </Record>
          ) : (
            <Talk
              key={m.id}
              labels={labels}
              footer={
                <>
                  {cancelled}
                  {footer}
                </>
              }
            >
              <Markdown>{m.content}</Markdown>
            </Talk>
          );
        })}

        {pending && <Turn>{pending.content}</Turn>}

        {(state.streaming || state.answer || state.error) && (
          <>
            {state.error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {labels.error}: {state.error}
              </div>
            ) : liveResearch ? (
              <Record
                mode="research"
                depth={pending?.depth}
                labels={labels}
                sources={state.sources}
                // Before grades land, the band shows one plain tick per source
                // read so far — the progress indicator and the bibliography are
                // the same object.
                pendingCount={state.progress?.count ?? 0}
                costUsd={state.costUsd}
                status={liveStatus}
              >
                {state.answer}
              </Record>
            ) : (
              <Talk labels={labels}>
                <Markdown>{state.answer}</Markdown>
                {state.streaming && !state.answer && (
                  <span className="font-mono text-[10.5px] text-slate-400">{labels.streaming}</span>
                )}
              </Talk>
            )}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      <Composer
        labels={labels}
        streaming={state.streaming}
        onSend={onSend}
        onCancel={() => {
          // Two halves: tell the server to stop the graph (it flags the thread,
          // and the run finalises itself as `cancelled`), and stop reading here.
          if (currentThread) void cancelChat(currentThread);
          detach();
        }}
      />
    </div>
  );
}
