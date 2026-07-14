import { getTranslations } from 'next-intl/server';
import { PostsTable, type PostRow } from '@/components/PostsTable';
import { Card, PageHeader } from '@/components/ui';
import { getRecentPosts } from '@/lib/data';

export default async function PostsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, tc, posts] = await Promise.all([
    getTranslations('posts'),
    getTranslations('common'),
    getRecentPosts(50),
  ]);

  const rows: PostRow[] = posts.map((p) => ({
    id: p.id,
    status: p.status,
    title: p.title,
    format: p.format,
    categoryId: p.categoryId,
    createdAt: p.createdAt ?? '',
    costUsd: p.tokenUsage?.costUsd ?? null,
    channels: Object.entries(p.channels).map(([name, ch]) => ({
      name,
      status: ch.status,
      url: ch.url,
    })),
  }));

  return (
    <div>
      <PageHeader title={t('title')} hint={t('hint')} />
      <Card flush>
        <PostsTable
          posts={rows}
          locale={locale}
          labels={{
            status: tc('status'),
            title: tc('title'),
            format: tc('format'),
            channels: t('channelStatus'),
            cost: t('cost'),
            created: tc('created'),
            empty: t('empty'),
            deleteSelected: t('deleteSelected'),
            confirmDelete: t('confirmDeletePosts'),
            selected: t('selectedCount'),
          }}
        />
      </Card>
    </div>
  );
}
