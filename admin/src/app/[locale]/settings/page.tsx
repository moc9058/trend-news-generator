import { getTranslations } from 'next-intl/server';
import { ActionButton } from '@/components/ActionButton';
import { Card, btnCls, inputCls } from '@/components/ui';
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
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t('title')}</h1>

      <Card title={t('app')}>
        <form action={saveAppSettings} className="max-w-xl space-y-3 text-sm">
          <label className="block">
            {t('timezone')}
            <input name="timezone" defaultValue={settings.timezone} className={inputCls} />
          </label>
          <label className="flex items-center gap-2">
            <input name="dailyRequireApproval" type="checkbox"
              defaultChecked={settings.dailyRequireApproval} />
            {t('dailyRequireApproval')}
          </label>
          <label className="flex items-center gap-2">
            <input name="xAllowUrlOnDaily" type="checkbox"
              defaultChecked={settings.xAllowUrlOnDaily} />
            {t('xAllowUrlOnDaily')}
          </label>
          <label className="flex items-center gap-2">
            <input name="attachImages" type="checkbox"
              defaultChecked={settings.attachImages} />
            {t('attachImages')}
          </label>
          <label className="block">
            {t('notionDatabaseId')}
            <input name="notionDatabaseId" defaultValue={notionDbId} className={inputCls} />
          </label>
          <button type="submit" className={btnCls}>{tc('save')}</button>
        </form>
      </Card>

      <Card title={t('jobs')}>
        <div className="flex flex-wrap gap-3">
          {JOB_TYPES.map((job) => (
            <ActionButton
              key={job}
              action={runJobNow.bind(null, job)}
              label={`${job} ▶`}
              secondary
            />
          ))}
        </div>
      </Card>
    </div>
  );
}
