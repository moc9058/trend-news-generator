import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { Icon } from '@/components/icons';
import { Card, Chip, EmptyState, PageHeader, StatusBadge, Table, tdCls, thCls } from '@/components/ui';
import { retryChannel } from '@/lib/actions';
import { getRecentPosts } from '@/lib/data';

export default async function PostsPage() {
  const [t, tc, posts] = await Promise.all([
    getTranslations('posts'),
    getTranslations('common'),
    getRecentPosts(50),
  ]);

  return (
    <div>
      <PageHeader title={t('title')} />
      <Card flush>
        {posts.length === 0 ? (
          <EmptyState message={t('empty')} />
        ) : (
          <Table>
            <thead>
              <tr>
                <th className={thCls}>{tc('status')}</th>
                <th className={thCls}>{tc('title')}</th>
                <th className={thCls}>{tc('format')}</th>
                <th className={thCls}>{t('channelStatus')}</th>
                <th className={thCls}>{t('cost')}</th>
                <th className={thCls}>{tc('created')}</th>
              </tr>
            </thead>
            <tbody>
              {posts.map((p) => (
                <tr key={p.id} className="align-top transition-colors hover:bg-paper/50">
                  <td className={tdCls}>
                    <StatusBadge status={p.status} />
                  </td>
                  <td className={`${tdCls} max-w-xs`}>
                    <div className="truncate text-[13px] font-medium text-ink">{p.title || p.id}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-slate-400">{p.categoryId}</div>
                  </td>
                  <td className={tdCls}>
                    <Chip>{p.format}</Chip>
                  </td>
                  <td className={tdCls}>
                    <div className="space-y-1.5">
                      {Object.entries(p.channels).map(([name, ch]) => (
                        <div key={name} className="flex items-center gap-2 text-xs">
                          <span className="w-14 font-mono text-slate-500">{name}</span>
                          <StatusBadge status={ch.status} />
                          {ch.url && (
                            <a
                              href={ch.url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 font-medium text-accent underline-offset-2 hover:underline"
                            >
                              <Icon name="external" size={12} />
                              link
                            </a>
                          )}
                          {ch.status === 'failed' && (
                            <>
                              <span className="max-w-48 truncate text-red-600" title={ch.error}>
                                {ch.error}
                              </span>
                              <ActionButton
                                action={retryChannel.bind(null, p.id, name)}
                                label={tc('retry')}
                                secondary
                              />
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  </td>
                  <td className={`${tdCls} font-mono text-xs text-slate-500`}>
                    ${p.tokenUsage?.costUsd?.toFixed(3) ?? '—'}
                  </td>
                  <td className={`${tdCls} font-mono text-xs text-slate-400`}>
                    {p.createdAt.slice(0, 16).replace('T', ' ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
