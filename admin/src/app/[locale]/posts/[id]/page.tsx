import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { Icon } from '@/components/icons';
import { Markdown } from '@/components/Markdown';
import { Card, Chip, PageHeader, StatusBadge, linkCls } from '@/components/ui';
import { deletePostChannels, deletePosts, retryChannel } from '@/lib/actions';
import { getPost } from '@/lib/data';

const CHANNEL_LABELS: Record<string, string> = { x: 'X', threads: 'Threads', notion: 'Notion' };

export default async function PostDetailPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { locale, id } = await params;
  const [t, tc, post] = await Promise.all([
    getTranslations('posts'),
    getTranslations('common'),
    getPost(id),
  ]);
  if (!post) notFound();

  const localizations = Object.entries(post.localizations ?? {}).filter(
    ([, loc]) => loc.title || loc.body,
  );

  return (
    <div className="space-y-5">
      <PageHeader title={post.title || post.id}>
        <ActionButton
          action={deletePosts.bind(null, [post.id])}
          label={t('deletePost')}
          confirmText={t('confirmDeletePosts')}
          secondary
        />
      </PageHeader>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge status={post.status} />
        <Chip>{post.format}</Chip>
        <Chip>{post.categoryId}</Chip>
        {post.tokenUsage && (
          <span className="font-mono text-xs text-fg-muted">
            ${post.tokenUsage.costUsd?.toFixed(3)}
          </span>
        )}
        <span className="font-mono text-xs text-fg-faint">
          {post.createdAt?.slice(0, 16).replace('T', ' ')}
        </span>
        {post.researchRunId && (
          <Link href={`/${locale}/research/${post.researchRunId}`} className={linkCls}>
            {t('researchRun')} →
          </Link>
        )}
      </div>

      <Card title={t('channels')}>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {Object.entries(post.channels).map(([name, ch]) => (
            <div
              key={name}
              className="flex flex-col gap-2.5 rounded-xl border border-line bg-paper/50 p-4"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-fg">
                  {CHANNEL_LABELS[name] ?? name}
                </span>
                <StatusBadge status={ch.status} />
              </div>
              {ch.text && (
                <p className="whitespace-pre-wrap rounded-lg bg-surface p-3 text-xs leading-relaxed text-fg-muted shadow-card">
                  {ch.text}
                </p>
              )}
              {ch.error && (
                <p className="break-words text-xs text-red-300">{ch.error.slice(0, 300)}</p>
              )}
              <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
                {ch.url && (
                  <a
                    href={ch.url}
                    target="_blank"
                    rel="noreferrer"
                    className={`${linkCls} inline-flex items-center gap-1 text-xs`}
                  >
                    <Icon name="external" size={12} />
                    {t('openExternal')}
                  </a>
                )}
                {ch.status === 'failed' && (
                  <ActionButton
                    action={retryChannel.bind(null, post.id, name)}
                    label={tc('retry')}
                    secondary
                  />
                )}
                {ch.status === 'published' && (
                  <ActionButton
                    action={deletePostChannels.bind(null, post.id, [name])}
                    label={t('deleteChannel')}
                    confirmText={t('confirmDeleteChannel')}
                    secondary
                  />
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {post.summary && (
        <Card title={t('summary')}>
          <Markdown>{post.summary}</Markdown>
        </Card>
      )}

      {post.body && post.body !== post.summary && (
        <Card title={t('body')}>
          <Markdown>{post.body}</Markdown>
        </Card>
      )}

      {localizations.map(([lang, loc]) => (
        <Card key={lang} title={`${t('localization')} — ${lang.toUpperCase()}`}>
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-base font-bold text-fg">{loc.title}</span>
              {loc.url && (
                <a
                  href={loc.url}
                  target="_blank"
                  rel="noreferrer"
                  className={`${linkCls} inline-flex items-center gap-1 text-xs`}
                >
                  <Icon name="external" size={12} />
                  Notion
                </a>
              )}
            </div>
            {loc.summary && <Markdown>{loc.summary}</Markdown>}
            {loc.body && <Markdown>{loc.body}</Markdown>}
          </div>
        </Card>
      ))}
    </div>
  );
}
