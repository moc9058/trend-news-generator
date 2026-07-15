import Link from 'next/link';
import { Icon } from '@/components/icons';
import { btnSecondaryCls } from '@/components/ui';
import type { ChatThread } from '@/lib/types';

export function ThreadList({
  threads, activeId, locale, labels,
}: {
  threads: ChatThread[];
  activeId?: string;
  locale: string;
  labels: { newChat: string; noThreads: string; untitled: string };
}) {
  return (
    <div className="space-y-2">
      <Link href={`/${locale}/chat`} className={`${btnSecondaryCls} w-full`}>
        <Icon name="chat" size={13} />
        {labels.newChat}
      </Link>
      {threads.length === 0 ? (
        <p className="px-1 py-2 text-xs text-slate-400">{labels.noThreads}</p>
      ) : (
        <ul className="space-y-0.5">
          {threads.map((th) => (
            <li key={th.id}>
              <Link
                href={`/${locale}/chat/${th.id}`}
                className={`block truncate rounded-lg px-2.5 py-1.5 text-xs transition-colors ${
                  th.id === activeId
                    ? 'bg-accent-soft font-medium text-accent'
                    : 'text-slate-600 hover:bg-paper/60'
                }`}
              >
                {th.title || labels.untitled}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
