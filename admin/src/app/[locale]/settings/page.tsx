import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { btnCls, Card, inputCls, labelCls, PageHeader } from '@/components/ui';
import { JOB_TYPES } from '@/lib/constants';
import { runJobNow, saveAppSettings } from '@/lib/actions';
import { getAppSettings, getNotionDatabaseId } from '@/lib/data';

export default async function SettingsPage() {
  const [t, tc, settings, notionDbId] = await Promise.all([
    getTranslations('settings'),
    getTranslations('common'),
    getAppSettings(),
    getNotionDatabaseId(),
  ]);

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} />

      <Card title={t('app')}>
        <form action={saveAppSettings} className="max-w-xl space-y-4 text-sm">
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
          <button type="submit" className={btnCls}>{tc('save')}</button>
        </form>
      </Card>

      <Card title={t('jobs')}>
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
    </div>
  );
}
