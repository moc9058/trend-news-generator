'use client';

import { useState } from 'react';
import { Icon } from '@/components/icons';
import { btnCls, btnSecondaryCls } from '@/components/ui';

export interface ComposerLabels {
  modeChat: string;
  modeResearch: string;
  modeChatHint: string;
  modeResearchHint: string;
  depthQuick: string;
  depthDeep: string;
  depthQuickHint: string;
  depthDeepHint: string;
  placeholder: string;
  placeholderResearch: string;
  send: string;
  cancel: string;
}

function Toggle({
  active, onClick, title, children,
}: {
  active: boolean;
  onClick: () => void;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
        active
          ? 'bg-accent-soft text-accent ring-1 ring-inset ring-accent-line'
          : 'text-fg-muted hover:bg-surface-2 hover:text-fg'
      }`}
    >
      {children}
    </button>
  );
}

export function Composer({
  labels, streaming, onSend, onCancel,
}: {
  labels: ComposerLabels;
  streaming: boolean;
  onSend: (args: { content: string; mode: string; depth: string }) => void;
  onCancel: () => void;
}) {
  const [content, setContent] = useState('');
  const [mode, setMode] = useState('chat');
  const [depth, setDepth] = useState('quick');
  const research = mode === 'research';

  const submit = () => {
    const text = content.trim();
    if (!text || streaming) return;
    setContent('');
    onSend({ content: text, mode, depth });
  };

  return (
    <div className="rounded-xl border border-line bg-surface shadow-card focus-within:border-accent-line focus-within:ring-2 focus-within:ring-accent/20">
      <textarea
        rows={2}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={(e) => {
          // Enter sends; Shift+Enter (and IME composition) inserts a newline.
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={research ? labels.placeholderResearch : labels.placeholder}
        className="block w-full resize-none rounded-t-xl bg-transparent px-3.5 py-3 text-sm text-fg placeholder:text-fg-faint focus:outline-none"
      />
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line/60 px-2.5 py-2">
        <div className="flex flex-wrap items-center gap-1">
          <div className="flex items-center gap-0.5 rounded-lg bg-surface-2/60 p-0.5">
            <Toggle active={!research} onClick={() => setMode('chat')} title={labels.modeChatHint}>
              {labels.modeChat}
            </Toggle>
            <Toggle
              active={research}
              onClick={() => setMode('research')}
              title={labels.modeResearchHint}
            >
              {labels.modeResearch}
            </Toggle>
          </div>
          {research && (
            <div className="flex items-center gap-0.5 rounded-lg bg-surface-2/60 p-0.5">
              <Toggle
                active={depth === 'quick'}
                onClick={() => setDepth('quick')}
                title={labels.depthQuickHint}
              >
                {labels.depthQuick}
              </Toggle>
              <Toggle
                active={depth === 'deep'}
                onClick={() => setDepth('deep')}
                title={labels.depthDeepHint}
              >
                {labels.depthDeep}
              </Toggle>
            </div>
          )}
        </div>
        {streaming ? (
          <button type="button" className={btnSecondaryCls} onClick={onCancel}>
            <Icon name="stop" size={13} />
            {labels.cancel}
          </button>
        ) : (
          <button
            type="button"
            className={btnCls}
            onClick={submit}
            disabled={!content.trim()}
          >
            <Icon name="send" size={13} />
            {labels.send}
          </button>
        )}
      </div>
    </div>
  );
}
