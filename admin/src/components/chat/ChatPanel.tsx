import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { Card, linkCls } from '@/components/ui';
import { getCategories } from '@/lib/data';
import { ChatView } from './ChatView';
import { chatLabels } from './labels';

/** Dashboard panel: a fresh thread, always. Continuing a conversation is what
 * the full page is for, so this stays a scratchpad that never loads history. */
export async function ChatPanel({ locale }: { locale: string }) {
  const [t, labels, categories] = await Promise.all([
    getTranslations({ locale, namespace: 'chat' }),
    chatLabels(locale),
    getCategories(),
  ]);

  return (
    <Card
      title={t('title')}
      hint={t('subtitle')}
      actions={
        <Link href={`/${locale}/chat`} className={`${linkCls} text-xs`}>
          {t('openFull')}
        </Link>
      }
    >
      <div className="flex min-h-0 flex-col">
        <ChatView
          initialMessages={[]}
          labels={labels}
          categories={categories}
          locale={locale}
          compact
        />
      </div>
    </Card>
  );
}
