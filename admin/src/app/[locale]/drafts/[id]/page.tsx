import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';
import { DraftEditor } from '@/components/DraftEditor';
import { ReportDraftEditor } from '@/components/ReportDraftEditor';
import { Chip, StatusBadge } from '@/components/ui';
import { getPost } from '@/lib/data';

export default async function DraftDetailPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { id } = await params;
  const [t, post] = await Promise.all([getTranslations('drafts'), getPost(id)]);
  if (!post) notFound();

  return (
    <div>
      <header className="mb-6 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold tracking-tight text-fg">{t('editDraft')}</h1>
        <StatusBadge status={post.status} />
        <Chip>{post.format}</Chip>
        <span className="font-mono text-xs text-fg-faint">
          {post.categoryId} · ${post.tokenUsage?.costUsd?.toFixed(3) ?? '0'}
        </span>
      </header>
      {post.format === 'report' && post.localizations && Object.keys(post.localizations).length > 0
        ? <ReportDraftEditor post={post} />
        : <DraftEditor post={post} />}
    </div>
  );
}
