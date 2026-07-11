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
        {pending ? '…' : label}
      </button>
      {result && (
        <span className={`text-xs ${result.ok ? 'text-emerald-700' : 'text-red-700'}`}>
          {result.ok ? 'OK' : result.detail.slice(0, 200)}
        </span>
      )}
    </span>
  );
}
