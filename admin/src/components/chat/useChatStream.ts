'use client';

/** Client half of the chat SSE protocol (design doc 11 §5.4).
 *
 * EventSource is not an option: it only issues GETs, and a message carries a
 * JSON body. So we fetch(POST) and hand-parse the SSE framing off the response
 * reader — `event:`/`data:` lines, blocks split by a blank line, `:` comments
 * (our keep-alive pings) ignored.
 */

import { useCallback, useRef, useState } from 'react';
import type { ChatSource } from '@/lib/types';

export type ChatStage =
  | 'planning' | 'searching' | 'selecting' | 'reading' | 'gap_check' | 'synthesizing';

export interface StreamProgress {
  stage: ChatStage;
  connector?: string;
  query?: string;
  url?: string;
  count?: number;
}

export interface StreamState {
  streaming: boolean;
  answer: string;
  sources: ChatSource[];
  progress: StreamProgress | null;
  error: string;
  threadId: string;
  /** From the `meta` event — lets the view hand the live node off to the
   *  authoritative server copy once Firestore has the finished message. */
  assistantMessageId: string;
  costUsd: number | null;
}

const EMPTY: StreamState = {
  streaming: false, answer: '', sources: [], progress: null, error: '',
  threadId: '', assistantMessageId: '', costUsd: null,
};

export interface SendArgs {
  content: string;
  mode: string;
  depth: string;
  threadId?: string;
}

export function useChatStream(onThread?: (threadId: string) => void) {
  const [state, setState] = useState<StreamState>(EMPTY);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => setState(EMPTY), []);

  const send = useCallback(async (args: SendArgs) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ ...EMPTY, streaming: true });

    let resp: Response;
    try {
      resp = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(args),
        signal: controller.signal,
      });
    } catch (err) {
      setState((s) => ({ ...s, streaming: false, error: String(err) }));
      return;
    }

    if (!resp.ok || !resp.body) {
      const detail = await resp.text().catch(() => '');
      setState((s) => ({ ...s, streaming: false, error: detail || `HTTP ${resp.status}` }));
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const handle = (event: string, data: Record<string, unknown>) => {
      switch (event) {
        case 'meta': {
          const threadId = String(data.threadId ?? '');
          const assistantMessageId = String(data.assistantMessageId ?? '');
          setState((s) => ({ ...s, threadId, assistantMessageId }));
          if (threadId) onThread?.(threadId);
          break;
        }
        case 'token':
          setState((s) => ({ ...s, answer: s.answer + String(data.delta ?? '') }));
          break;
        case 'status':
          setState((s) => ({ ...s, progress: data as unknown as StreamProgress }));
          break;
        case 'sources':
          setState((s) => ({ ...s, sources: (data.sources ?? []) as ChatSource[] }));
          break;
        case 'usage':
          setState((s) => ({ ...s, costUsd: Number(data.costUsd ?? 0) }));
          break;
        case 'done':
          setState((s) => ({ ...s, streaming: false, progress: null }));
          break;
        case 'error':
          setState((s) => ({
            ...s, streaming: false, progress: null,
            error: String(data.message ?? 'unknown error'),
          }));
          break;
      }
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // A complete SSE block ends with a blank line; anything after the last
        // one is a partial block and stays buffered.
        const blocks = buffer.split('\n\n');
        buffer = blocks.pop() ?? '';
        for (const block of blocks) {
          let event = '';
          let raw = '';
          for (const line of block.split('\n')) {
            if (line.startsWith('event: ')) event = line.slice(7).trim();
            else if (line.startsWith('data: ')) raw += line.slice(6);
            // lines starting with ':' are keep-alive comments — ignore
          }
          if (!event) continue;
          try {
            handle(event, raw ? JSON.parse(raw) : {});
          } catch {
            // A malformed frame should not tear down a live answer.
          }
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setState((s) => ({ ...s, streaming: false, error: String(err) }));
      }
    }
    // The server may close without a `done` (client abort, proxy drop). Never
    // leave the composer stuck in a sending state.
    setState((s) => (s.streaming ? { ...s, streaming: false, progress: null } : s));
  }, [onThread]);

  /** Detach from the stream. The run itself keeps going server-side and its
   * result lands in Firestore — cancelling the *work* is the cancel action. */
  const detach = useCallback(() => {
    abortRef.current?.abort();
    setState((s) => ({ ...s, streaming: false, progress: null }));
  }, []);

  return { state, send, reset, detach };
}
