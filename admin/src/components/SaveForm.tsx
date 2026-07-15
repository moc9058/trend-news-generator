'use client';

import { useActionState } from 'react';
import type { ReactNode } from 'react';
import { btnCls } from './ui';

export type SaveResult = { ok: boolean; detail: string };

/** Wraps a server-action form with useActionState so every settings save
 * shows a pending spinner and a ✓/error result — instead of a silent
 * page re-render with no feedback. */
export function SaveForm({
  action,
  children,
  className,
  saveLabel,
  savedLabel,
  buttonClassName,
  footerClassName = 'mt-4 flex items-center gap-3',
  hint,
}: {
  action: (formData: FormData) => Promise<SaveResult>;
  children: ReactNode;
  className?: string;
  saveLabel: string;
  savedLabel: string;
  buttonClassName?: string;
  footerClassName?: string;
  hint?: ReactNode;
}) {
  const [state, formAction, isPending] = useActionState<SaveResult | null, FormData>(
    async (_prev, formData) => action(formData),
    null,
  );

  return (
    <form action={formAction} className={className}>
      {children}
      <div className={footerClassName}>
        <button type="submit" className={buttonClassName ?? btnCls} disabled={isPending}>
          {isPending && (
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent opacity-60" />
          )}
          {saveLabel}
        </button>
        {hint}
        {state && !isPending && (
          <span className={`font-mono text-xs ${state.ok ? 'text-emerald-600' : 'text-red-600'}`}>
            {state.ok ? `✓ ${savedLabel}` : state.detail.slice(0, 200)}
          </span>
        )}
      </div>
    </form>
  );
}
