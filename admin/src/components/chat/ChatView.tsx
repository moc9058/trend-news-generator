'use client';

/** The chat surface, shared by the dashboard panel (`compact`) and /chat/[id].
 *
 * A research answer is NOT a chat bubble. It is a record: a head strip (kind,
 * trust band, cost), a live phase rail while it works, the prose, then the
 * numbered apparatus. Sparring stays a plain conversational block with neither
 * band nor sources. The product's central distinction — is this just talk, or
 * is it backed by sources it actually read? — is therefore structural, readable
 * before a word is.
 *
 * The order (evidence, then prose) follows the data: the SSE contract emits
 * `sources` before the first `token`, so the band is populated by the time the
 * answer starts writing and nothing reflows.
 *
 * Messages already persisted arrive as `initialMessages` from a server
 * component. A turn started in this session streams live and is then kept in a
 * local `committed` list under a key that is stable for the whole turn — so the
 * live node and its finished form are the same element to React (the hand-off
 * neither flashes nor round-trips the server), and further turns work without a
 * navigation (the thread id is adopted into the URL via history.replaceState).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Markdown } from '@/components/Markdown';
import { EmptyState } from '@/components/ui';
import { cancelChat } from '@/lib/actions';
import type { Category, ChatMessage, ChatSource } from '@/lib/types';
import { Apparatus } from './Apparatus';
import { Composer, type ComposerLabels } from './Composer';
import { HandoffMenu, type HandoffLabels } from './HandoffMenu';
import { PhaseRail } from './PhaseRail';
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

/** A soft, blinking caret trailing the prose while it streams. */
function Caret() {
  return (
    <span
      aria-hidden
      className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[0.15em] animate-caret rounded-full bg-accent align-baseline"
    />
  );
}

/** What the user said. Quiet and set back — the question is context for the
 * answer, not a competing object. */
function Turn({ children }: { children: React.ReactNode }) {
  return (
    <p className="whitespace-pre-wrap border-l-2 border-line py-1 pl-3 text-sm text-fg-muted">
      {children}
    </p>
  );
}

function ErrorCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
      {children}
    </div>
  );
}

function CancelledNote({ children }: { children: React.ReactNode }) {
  return <p className="mt-1.5 font-mono text-[10.5px] text-fg-faint">{children}</p>;
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
  mode,
  depth,
  labels,
  sources,
  pendingCount,
  costUsd,
  rail,
  streaming,
  children,
  footer,
}: {
  mode: string;
  depth?: string | null;
  labels: ChatLabels;
  sources: ChatSource[];
  pendingCount?: number;
  costUsd?: number | null;
  rail?: React.ReactNode;
  streaming?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const [litN, setLitN] = useState<number | null>(null);
  return (
    <article className="min-w-0 rounded-2xl border border-line bg-surface px-4 py-3 shadow-card">
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
        {typeof costUsd === 'number' && (
          <span className="font-mono text-[10.5px] tabular-nums text-fg-faint">
            ${costUsd.toFixed(3)}
          </span>
        )}
      </div>
      {rail}
      <div className="pt-3 text-sm leading-[1.9] text-fg">
        <MarkdownWithCites litN={litN} onLit={setLitN}>
          {children}
        </MarkdownWithCites>
        {streaming && <Caret />}
      </div>
      <Apparatus sources={sources} litN={litN} onLit={setLitN} />
      {footer}
    </article>
  );
}

/** Bridges the cite handlers into Markdown only when the child is a string. */
function MarkdownWithCites({
  children,
  litN,
  onLit,
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
function Talk({
  labels,
  streaming,
  children,
  footer,
}: {
  labels: ChatLabels;
  streaming?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-2xl border border-line bg-surface px-4 py-3 shadow-card">
      <span className="mb-1.5 block font-mono text-[10.5px] uppercase tracking-[0.12em] text-fg-faint">
        {labels.modeChat}
      </span>
      <div className="text-sm leading-[1.9] text-fg">
        {children}
        {streaming && <Caret />}
      </div>
      {footer}
    </div>
  );
}

type Committed = { key: string; msg: ChatMessage };

export function ChatView({
  threadId,
  initialMessages,
  labels,
  categories,
  compact,
  locale,
}: {
  threadId?: string;
  initialMessages: ChatMessage[];
  labels: ChatLabels;
  categories: Category[];
  compact?: boolean;
  locale: string;
}) {
  const [currentThread, setCurrentThread] = useState(threadId ?? '');
  const { state, send, detach, reset } = useChatStream();

  // Turns finished in this session, kept under a key that is stable for the
  // whole turn (see file header). Server-persisted turns stay in initialMessages.
  const [committed, setCommitted] = useState<Committed[]>([]);
  // The locally-echoed user turn, shown the instant it is sent.
  const [pending, setPending] = useState<{ content: string; mode: string; depth: string } | null>(
    null,
  );
  const [turnKey, setTurnKey] = useState('');

  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const turnCount = useRef(0);
  const cancelRef = useRef(false);
  const committedRef = useRef(false);

  // Stick to the bottom only when the reader is already near it, so a scroll up
  // to re-read is not yanked back down mid-stream.
  const onScroll = () => {
    const el = scrollRef.current;
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 140;
  };
  useEffect(() => {
    if (stickRef.current) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [state.answer, state.progress, committed.length, pending]);

  // When the stream ends (done / error / abort), fold the finished turn into the
  // local committed list under the same turn key, then clear the transient state.
  // Same key + same position ⇒ React reuses the DOM: no flash, no server refresh.
  useEffect(() => {
    if (state.streaming) {
      committedRef.current = false;
      return;
    }
    if (committedRef.current || (!state.answer && !state.error)) return;
    committedRef.current = true;

    const status = state.error ? 'error' : cancelRef.current ? 'cancelled' : 'complete';
    const assistant: ChatMessage = {
      id: state.assistantMessageId || `${turnKey}-a`,
      seq: 0,
      role: 'assistant',
      mode: pending?.mode ?? 'chat',
      depth: pending?.depth ?? null,
      content: state.answer,
      status,
      sources: state.sources,
      usage:
        typeof state.costUsd === 'number'
          ? { costUsd: state.costUsd, promptTokens: 0, completionTokens: 0 }
          : null,
      handoffs: [],
      error: state.error || '',
    };
    const user: ChatMessage = {
      id: `${turnKey}-u`,
      seq: 0,
      role: 'user',
      mode: pending?.mode ?? 'chat',
      depth: pending?.depth ?? null,
      content: pending?.content ?? '',
      status: 'complete',
    };
    setCommitted((c) => [
      ...c,
      { key: `${turnKey}-u`, msg: user },
      { key: `${turnKey}-a`, msg: assistant },
    ]);
    setPending(null);
    cancelRef.current = false;
    reset();
  }, [
    state.streaming,
    state.answer,
    state.error,
    state.sources,
    state.costUsd,
    state.assistantMessageId,
    pending,
    turnKey,
    reset,
  ]);

  // A brand-new thread gets its id from the `meta` event; adopt it and reflect
  // it in the URL without a navigation, so the live stream keeps rendering.
  useEffect(() => {
    if (!state.threadId || state.threadId === currentThread) return;
    setCurrentThread(state.threadId);
    if (!compact && typeof window !== 'undefined') {
      window.history.replaceState(null, '', `/${locale}/chat/${state.threadId}`);
    }
  }, [state.threadId, currentThread, compact, locale]);

  const onSend = (args: { content: string; mode: string; depth: string }) => {
    const key = `turn-${(turnCount.current += 1)}`;
    setTurnKey(key);
    setPending(args);
    stickRef.current = true;
    void send({ ...args, threadId: currentThread || undefined }).then(() => undefined);
  };

  const renderMessage = useCallback(
    (m: ChatMessage): React.ReactNode => {
      if (m.role === 'user') return <Turn>{m.content}</Turn>;

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
          <ErrorCard>
            {labels.error}: {m.error}
          </ErrorCard>
        );
      }

      const cancelled =
        m.status === 'cancelled' ? <CancelledNote>{labels.cancelled}</CancelledNote> : null;

      return m.mode === 'research' ? (
        <Record
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
    },
    [categories, currentThread, labels, locale],
  );

  const liveResearch = pending?.mode === 'research';
  const liveNode = state.error ? (
    <ErrorCard>
      {labels.error}: {state.error}
    </ErrorCard>
  ) : liveResearch ? (
    <Record
      mode="research"
      depth={pending?.depth}
      labels={labels}
      sources={state.sources}
      // Before grades land, the band shows one plain tick per source read so far
      // — the progress indicator and the bibliography are the same object.
      pendingCount={state.progress?.count ?? 0}
      costUsd={state.costUsd}
      streaming={state.streaming}
      rail={
        state.progress ? (
          <PhaseRail progress={state.progress} labels={labels} deep={pending?.depth === 'deep'} />
        ) : null
      }
    >
      {state.answer}
    </Record>
  ) : (
    <Talk labels={labels} streaming={state.streaming}>
      <Markdown>{state.answer}</Markdown>
      {state.streaming && !state.answer && (
        <span className="ml-1 font-mono text-[10.5px] text-fg-faint">{labels.streaming}</span>
      )}
    </Talk>
  );

  const messages = [...initialMessages, ...committed.map((c) => c.msg)];
  const showPending = !!pending;
  const showLive = state.streaming || !!state.answer || !!state.error;
  const showEmpty = !messages.length && !showPending && !showLive;

  const items: { key: string; node: React.ReactNode }[] = [
    ...initialMessages.map((m) => ({ key: m.id, node: renderMessage(m) })),
    ...committed.map((c) => ({ key: c.key, node: renderMessage(c.msg) })),
  ];
  if (showPending) items.push({ key: `${turnKey}-u`, node: <Turn>{pending!.content}</Turn> });
  if (showLive) items.push({ key: `${turnKey}-a`, node: liveNode });

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className={`flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto ${
          compact ? 'max-h-80' : 'pr-1'
        }`}
      >
        {showEmpty && <EmptyState message={labels.empty} />}

        <AnimatePresence initial={false} mode="popLayout">
          {items.map((it) => (
            <motion.div
              key={it.key}
              layout={it.key !== `${turnKey}-a`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, transition: { duration: 0.12 } }}
              transition={{ duration: 0.24, ease: 'easeOut' }}
            >
              {it.node}
            </motion.div>
          ))}
        </AnimatePresence>

        <div ref={bottomRef} />
      </div>

      <Composer
        labels={labels}
        streaming={state.streaming}
        onSend={onSend}
        onCancel={() => {
          // Two halves: tell the server to stop the graph (it flags the thread,
          // and the run finalises itself as `cancelled`), and stop reading here.
          cancelRef.current = true;
          if (currentThread) void cancelChat(currentThread);
          detach();
        }}
      />
    </div>
  );
}
