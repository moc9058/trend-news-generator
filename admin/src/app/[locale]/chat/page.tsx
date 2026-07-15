import { getTranslations } from 'next-intl/server';
import { ChatView } from '@/components/chat/ChatView';
import { chatLabels } from '@/components/chat/labels';
import { ThreadList } from '@/components/chat/ThreadList';
import { Card, PageHeader } from '@/components/ui';
import { getCategories, getChatThreads } from '@/lib/data';

/** New conversation. Picking an existing one routes to /chat/[id]. */
export default async function ChatPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, labels, threads, categories] = await Promise.all([
    getTranslations({ locale, namespace: 'chat' }),
    chatLabels(locale),
    getChatThreads(),
    getCategories(),
  ]);

  return (
    <div>
      <PageHeader title={t('title')} hint={t('subtitle')} />
      {/* Sidebar collapses above the conversation on mobile — the `lg:` rule the
          rest of admin uses (AppShell). */}
      <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside>
          <ThreadList
            threads={threads}
            locale={locale}
            labels={{ newChat: t('newChat'), noThreads: t('noThreads'), untitled: t('untitled') }}
          />
        </aside>
        <Card>
          <div className="flex min-h-[60vh] flex-col">
            <ChatView
              initialMessages={[]}
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
