'use client';

/** The chat surface, shared by the dashboard panel (`compact`) and /chat/[id].
 *
 * Messages already persisted arrive as `initialMessages` from a server
 * component; the in-flight answer lives in `useChatStream` until it lands. On a
 * fresh thread the URL is swapped to /chat/{id} once the server names it.
 */

import { useEffect, useRef, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { Markdown } from '@/components/Markdown';
import { EmptyState } from '@/components/ui';
import { cancelChat } from '@/lib/actions';
import type { Category, ChatMessage } from '@/lib/types';
import { Composer, type ComposerLabels } from './Composer';
import { HandoffMenu, type HandoffLabels } from './HandoffMenu';
import { SourceList } from './SourceList';
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

function Bubble({ role, children }: { role: string; children: React.ReactNode }) {
  const user = role === 'user';
  return (
    <div className={`flex ${user ? 'justify-end' : 'justify-start'}`}>
      <div
        className={
          user
            ? 'max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-3.5 py-2 text-sm text-white shadow-card'
            : 'w-full min-w-0 rounded-2xl rounded-bl-sm border border-line bg-white px-3.5 py-2.5 shadow-card'
        }
      >
        {children}
      </div>
    </div>
  );
}

function ModeTag({ mode, depth, labels }: { mode: string; depth?: string | null; labels: ChatLabels }) {
  if (mode !== 'research') return null;
  return (
    <span className="mb-1.5 inline-flex items-center gap-1 rounded bg-accent-soft px-1.5 py-px text-[10px] font-medium text-accent">
      {labels.modeResearch}
      {depth ? ` · ${depth === 'deep' ? labels.depthDeep : labels.depthQuick}` : ''}
    </span>
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
  const stageDetail = state.progress?.connector ?? state.progress?.url ?? '';

  const showEmpty = !initialMessages.length && !pending && !state.answer;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className={`min-h-0 flex-1 space-y-3 overflow-y-auto ${compact ? 'max-h-80' : 'pr-1'}`}>
        {showEmpty && <EmptyState message={labels.empty} />}

        {initialMessages.map((m) => (
          <Bubble key={m.id} role={m.role}>
            {m.role === 'user' ? (
              <p className="whitespace-pre-wrap">{m.content}</p>
            ) : (
              <>
                <ModeTag mode={m.mode} depth={m.depth} labels={labels} />
                {m.status === 'error' ? (
                  <p className="text-sm text-red-600">
                    {labels.error}: {m.error}
                  </p>
                ) : (
                  <div className="text-sm leading-relaxed text-ink">
                    <Markdown>{m.content}</Markdown>
                  </div>
                )}
                {m.status === 'cancelled' && (
                  <p className="mt-1 text-xs text-slate-400">{labels.cancelled}</p>
                )}
                <SourceList sources={m.sources ?? []} label={labels.sources} />
                {m.status === 'complete' && m.content && (
                  <HandoffMenu
                    threadId={currentThread}
                    messageId={m.id}
                    categories={categories}
                    labels={labels}
                    locale={locale}
                    handoffs={m.handoffs ?? []}
                  />
                )}
              </>
            )}
          </Bubble>
        ))}

        {pending && (
          <Bubble role="user">
            <p className="whitespace-pre-wrap">{pending.content}</p>
          </Bubble>
        )}

        {(state.streaming || state.answer || state.error) && (
          <Bubble role="assistant">
            {pending?.mode === 'research' && (
              <ModeTag mode="research" depth={pending.depth} labels={labels} />
            )}
            {state.progress && (
              <p className="mb-1.5 flex items-center gap-1.5 text-xs text-slate-500">
                <span className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-accent border-t-transparent" />
                {stageLabel}
                {stageDetail && (
                  <span className="truncate font-mono text-[10px] text-slate-400">
                    {stageDetail}
                  </span>
                )}
              </p>
            )}
            {state.error ? (
              <p className="text-sm text-red-600">
                {labels.error}: {state.error}
              </p>
            ) : (
              <div className="text-sm leading-relaxed text-ink">
                <Markdown>{state.answer}</Markdown>
                {state.streaming && !state.answer && !state.progress && (
                  <span className="text-xs text-slate-400">{labels.streaming}</span>
                )}
              </div>
            )}
            <SourceList sources={state.sources} label={labels.sources} />
            {state.costUsd !== null && (
              <p className="mt-2 font-mono text-[10px] text-slate-400">
                {labels.costLabel} ${state.costUsd.toFixed(3)}
              </p>
            )}
          </Bubble>
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
