import { getTranslations } from 'next-intl/server';
import { Card } from '@/components/ui';
import { CADENCES, CHANNELS, LANGUAGES } from '@/lib/constants';
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
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t('title')}</h1>
      <p className="text-xs text-slate-500">{t('hint')}</p>
      {categories.map((cat) => (
        <Card key={cat.slug} title={cat.name}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-1">{tc('cadence')}</th>
                {CHANNELS.map((ch) => <th key={ch}>{ch}</th>)}
              </tr>
            </thead>
            <tbody>
              {CADENCES.map((cadence) => (
                <tr key={cadence} className="border-t border-slate-100">
                  <td className="py-2 text-xs font-medium">{cadence}</td>
                  {CHANNELS.map((channel) => {
                    const id = `${cat.slug}_${cadence}_${channel}`;
                    const cfg = byId.get(id);
                    return (
                      <td key={channel} className="py-2 pr-4">
                        <form
                          action={async (formData: FormData) => {
                            'use server';
                            await saveChannelConfig(
                              id, cat.slug, cadence, channel,
                              formData.get('enabled') === 'on',
                              String(formData.get('language') ?? 'en'),
                            );
                          }}
                          className="flex items-center gap-2"
                        >
                          <input
                            name="enabled" type="checkbox"
                            defaultChecked={cfg?.enabled ?? false}
                          />
                          <select
                            name="language" defaultValue={cfg?.language ?? 'en'}
                            className="rounded border border-slate-300 px-1 py-0.5 text-xs"
                          >
                            {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
                          </select>
                          <button className="text-xs text-sky-700 underline">
                            {tc('save')}
                          </button>
                        </form>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      ))}
    </div>
  );
}
