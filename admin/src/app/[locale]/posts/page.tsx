import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { Card, StatusBadge } from '@/components/ui';
import { retryChannel } from '@/lib/actions';
import { getRecentPosts } from '@/lib/data';

export default async function PostsPage() {
  const [t, tc, posts] = await Promise.all([
    getTranslations('posts'),
    getTranslations('common'),
    getRecentPosts(50),
  ]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t('title')}</h1>
      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th className="py-1">{tc('status')}</th>
              <th>{tc('title')}</th>
              <th>{tc('cadence')}</th>
              <th>{t('channelStatus')}</th>
              <th>{t('cost')}</th>
              <th>{tc('created')}</th>
            </tr>
          </thead>
          <tbody>
            {posts.map((p) => (
              <tr key={p.id} className="border-t border-slate-100 align-top">
                <td className="py-2"><StatusBadge status={p.status} /></td>
                <td className="max-w-xs">
                  <div className="truncate">{p.title || p.id}</div>
                  <div className="text-xs text-slate-400">{p.categoryId}</div>
                </td>
                <td className="text-xs">{p.cadence}</td>
                <td>
                  <div className="space-y-1">
                    {Object.entries(p.channels).map(([name, ch]) => (
                      <div key={name} className="flex items-center gap-2 text-xs">
                        <span className="w-14 font-mono">{name}</span>
                        <StatusBadge status={ch.status} />
                        {ch.url && (
                          <a href={ch.url} target="_blank" rel="noreferrer"
                            className="text-sky-700 underline">link</a>
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
                <td className="text-xs">${p.tokenUsage?.costUsd?.toFixed(3) ?? '—'}</td>
                <td className="text-xs text-slate-400">
                  {p.createdAt.slice(0, 16).replace('T', ' ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
