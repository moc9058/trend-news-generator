import { getTranslations } from 'next-intl/server';
import { Card, PageHeader, Table, tdCls, thCls } from '@/components/ui';
import { FORMATS, CHANNELS, LANGUAGES } from '@/lib/constants';
import { saveChannelConfig } from '@/lib/actions';
import { getCategories, getChannelConfigs } from '@/lib/data';

export default async function ChannelsPage() {
  const [t, tc, categories, configs] = await Promise.all([
    getTranslations('channels'),
    getTranslations('common'),
    getCategories(),
    getChannelConfigs(),
  ]);
  const byId = new Map(configs.map((c) => [c.id, c]));

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} hint={t('hint')} />
      {categories.map((cat) => (
        <Card key={cat.slug} title={cat.name} flush>
          <Table>
            <thead>
              <tr>
                <th className={thCls}>{tc('format')}</th>
                {CHANNELS.map((ch) => (
                  <th key={ch} className={`${thCls} font-mono normal-case`}>{ch}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {FORMATS.map((fmt) => (
                <tr key={fmt}>
                  <td className={`${tdCls} font-mono text-xs font-medium text-ink`}>{fmt}</td>
                  {CHANNELS.map((channel) => {
                    const id = `${cat.slug}_${fmt}_${channel}`;
                    const cfg = byId.get(id);
                    return (
                      <td key={channel} className={tdCls}>
                        <form
                          action={async (formData: FormData) => {
                            'use server';
                            await saveChannelConfig(
                              id, cat.slug, fmt, channel,
                              formData.get('enabled') === 'on',
                              String(formData.get('language') ?? 'en'),
                            );
                          }}
                          className="flex items-center gap-2.5"
                        >
                          <input
                            name="enabled"
                            type="checkbox"
                            defaultChecked={cfg?.enabled ?? false}
                            className="h-4 w-4 rounded border-line"
                          />
                          <select
                            name="language"
                            defaultValue={cfg?.language ?? 'en'}
                            className="rounded-md border border-line bg-white px-1.5 py-1 font-mono text-xs text-slate-700 focus:border-accent focus:outline-none"
                          >
                            {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
                          </select>
                          <button className="rounded-md px-2 py-1 text-xs font-medium text-accent transition-colors hover:bg-accent-soft">
                            {tc('save')}
                          </button>
                        </form>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      ))}
    </div>
  );
}
