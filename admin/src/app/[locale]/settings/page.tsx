import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { Icon, type IconName } from '@/components/icons';
import { SaveForm } from '@/components/SaveForm';
import { Card, inputCls, labelCls, PageHeader, Table, tdCls } from '@/components/ui';
import { JOB_TYPES } from '@/lib/constants';
import { runJobNow, saveAppSettings } from '@/lib/actions';
import { getAppSettings, getNotionDatabaseId, getRecentRuns } from '@/lib/data';

const fmtDate = (iso?: string) => (iso ? iso.slice(0, 16).replace('T', ' ') : '');

const CHANNEL_META: { key: 'notion' | 'x' | 'threads'; label: string }[] = [
  { key: 'notion', label: 'Notion' },
  { key: 'x', label: 'X' },
  { key: 'threads', label: 'Threads' },
];

const ADVANCED_LINKS: { href: string; key: string; icon: IconName }[] = [
  { href: '/categories', key: 'categories', icon: 'categories' },
  { href: '/sources', key: 'sources', icon: 'sources' },
  { href: '/prompts', key: 'prompts', icon: 'prompts' },
  { href: '/channels', key: 'channels', icon: 'channels' },
  { href: '/research', key: 'research', icon: 'research' },
];

export default async function SettingsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, tc, tn, settings, notionDbId, runs] = await Promise.all([
    getTranslations('settings'),
    getTranslations('common'),
    getTranslations('nav'),
    getAppSettings(),
    getNotionDatabaseId(),
    getRecentRuns(12),
  ]);

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} />

      <Card title={t('globalChannels')} hint={t('globalChannelsHint')}>
        <SaveForm
          action={saveAppSettings}
          saveLabel={tc('save')}
          savedLabel={tc('saved')}
          className="space-y-4 text-sm"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {CHANNEL_META.map(({ key, label }) => (
              <label
                key={key}
                className="flex cursor-pointer items-center gap-3 rounded-xl border border-line bg-paper/60 px-4 py-3 transition-colors has-[:checked]:border-accent-line has-[:checked]:bg-accent-soft"
              >
                <input
                  name={`channel_${key}`}
                  type="checkbox"
                  defaultChecked={settings.globalChannels[key]}
                  className="h-4 w-4 rounded border-line"
                />
                <span className="text-sm font-semibold text-ink">{label}</span>
              </label>
            ))}
          </div>

          <div className="border-t border-line pt-4">
            <h3 className="mb-3 text-sm font-semibold text-ink">{t('app')}</h3>
            <div className="max-w-xl space-y-4">
              <label className={labelCls}>
                {t('timezone')}
                <input name="timezone" defaultValue={settings.timezone} className={inputCls} />
              </label>
              <div className="space-y-2.5 rounded-xl border border-line bg-paper/60 p-4">
                <label className="flex items-center gap-2.5 text-sm text-slate-700">
                  <input
                    name="shortRequireApproval"
                    type="checkbox"
                    defaultChecked={settings.shortRequireApproval}
                    className="h-4 w-4 rounded border-line"
                  />
                  {t('shortRequireApproval')}
                </label>
                <label className="flex items-center gap-2.5 text-sm text-slate-700">
                  <input
                    name="xAllowUrlOnShort"
                    type="checkbox"
                    defaultChecked={settings.xAllowUrlOnShort}
                    className="h-4 w-4 rounded border-line"
                  />
                  {t('xAllowUrlOnShort')}
                </label>
                <label className="flex items-center gap-2.5 text-sm text-slate-700">
                  <input
                    name="attachImages"
                    type="checkbox"
                    defaultChecked={settings.attachImages}
                    className="h-4 w-4 rounded border-line"
                  />
                  {t('attachImages')}
                </label>
              </div>
              <label className={labelCls}>
                {t('notionDatabaseId')}
                <input name="notionDatabaseId" defaultValue={notionDbId} className={inputCls} />
              </label>
            </div>
          </div>
        </SaveForm>
      </Card>

      <Card title={t('advanced')} hint={t('advancedHint')}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {ADVANCED_LINKS.map(({ href, key, icon }) => (
            <Link
              key={key}
              href={`/${locale}${href}`}
              className="group flex flex-col items-start gap-2 rounded-xl border border-line bg-paper/50 p-4 transition-all hover:border-accent-line hover:bg-accent-soft hover:shadow-card"
            >
              <Icon name={icon} size={18} className="text-slate-400 group-hover:text-accent" />
              <span className="text-sm font-medium text-ink group-hover:text-accent">
                {tn(key)}
              </span>
            </Link>
          ))}
        </div>
      </Card>

      <Card title={t('jobs')} hint={t('jobsHint')}>
        <div className="flex flex-wrap gap-2.5">
          {JOB_TYPES.map((job) => (
            <ActionButton
              key={job}
              action={runJobNow.bind(null, job)}
              label={`▶ ${job}`}
              secondary
            />
          ))}
        </div>
      </Card>

      <Card title={t('recentRuns')} flush>
        <Table>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td className={`${tdCls} w-44 font-mono text-xs text-ink`}>{r.jobType}</td>
                <td className={`${tdCls} w-24`}>
                  <span
                    className={`inline-flex items-center gap-1.5 font-mono text-xs font-medium ${
                      r.ok ? 'text-emerald-700' : 'text-red-600'
                    }`}
                  >
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${r.ok ? 'bg-emerald-500' : 'bg-red-500'}`}
                    />
                    {r.ok ? 'ok' : 'failed'}
                  </span>
                </td>
                <td className={`${tdCls} w-40 font-mono text-xs text-slate-400`}>
                  {fmtDate(r.startedAt)}
                </td>
                <td className={`${tdCls} text-xs text-slate-500`}>
                  <span className="font-mono">{r.stats ? JSON.stringify(r.stats) : ''}</span>
                  {r.errors && r.errors.length > 0 && (
                    <span className="text-red-600"> {r.errors[0]?.slice(0, 80)}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
