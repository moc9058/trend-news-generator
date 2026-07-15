import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';
import { ChatView } from '@/components/chat/ChatView';
import { chatLabels } from '@/components/chat/labels';
import { ThreadList } from '@/components/chat/ThreadList';
import { Card, PageHeader } from '@/components/ui';
import { getCategories, getChatMessages, getChatThread, getChatThreads } from '@/lib/data';

export default async function ChatThreadPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  const [t, thread] = await Promise.all([
    getTranslations({ locale, namespace: 'chat' }),
    getChatThread(id),
  ]);
  if (!thread) notFound();

  const [labels, threads, messages, categories] = await Promise.all([
    chatLabels(locale),
    getChatThreads(),
    getChatMessages(id),
    getCategories(),
  ]);

  const cost = thread.totals?.costUsd ?? 0;

  return (
    <div>
      <PageHeader
        title={thread.title || t('untitled')}
        hint={cost ? `${t('costLabel')} $${cost.toFixed(3)}` : undefined}
      />
      <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside>
          <ThreadList
            threads={threads}
            activeId={id}
            locale={locale}
            labels={{ newChat: t('newChat'), noThreads: t('noThreads'), untitled: t('untitled') }}
          />
        </aside>
        <Card>
          <div className="flex min-h-[60vh] flex-col">
            <ChatView
              threadId={id}
              initialMessages={messages}
              labels={labels}
              categories={categories}
              locale={locale}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}
