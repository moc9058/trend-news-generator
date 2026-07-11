import { notFound } from 'next/navigation';
import { getTranslations } from 'next-intl/server';
import { DraftEditor } from '@/components/DraftEditor';
import { StatusBadge } from '@/components/ui';
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
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-bold">{t('editDraft')}</h1>
        <StatusBadge status={post.status} />
        <span className="text-xs text-slate-400">
          {post.cadence} / {post.categoryId} / ${post.tokenUsage?.costUsd?.toFixed(3) ?? '0'}
        </span>
      </div>
      <DraftEditor post={post} />
    </div>
  );
}
