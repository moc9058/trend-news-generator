'use client';

import { useState, useTransition } from 'react';
import { btnCls, btnSecondaryCls } from './ui';

export function ActionButton({
  action,
  label,
  confirmText,
  secondary,
}: {
  action: () => Promise<{ ok: boolean; detail: string }>;
  label: string;
  confirmText?: string;
  secondary?: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<{ ok: boolean; detail: string } | null>(null);

  return (
    <span className="inline-flex items-center gap-2">
      <button
        className={secondary ? btnSecondaryCls : btnCls}
        disabled={pending}
        onClick={() => {
          if (confirmText && !window.confirm(confirmText)) return;
          startTransition(async () => setResult(await action()));
        }}
      >
        {pending && (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent opacity-60" />
        )}
        {label}
      </button>
      {result && (
        <span
          className={`font-mono text-xs ${result.ok ? 'text-emerald-600' : 'text-red-600'}`}
        >
          {result.ok ? '✓' : result.detail.slice(0, 200)}
        </span>
      )}
    </span>
  );
}
