import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { Card, StatusBadge } from '@/components/ui';
import { CADENCES } from '@/lib/constants';
import { getCategories, getPromptTemplates } from '@/lib/data';

export default async function PromptsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, templates, categories] = await Promise.all([
    getTranslations('prompts'),
    getPromptTemplates(),
    getCategories(),
  ]);
  const byId = new Map(templates.map((tpl) => [tpl.id, tpl]));

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{t('title')}</h1>
      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th className="py-1"></th>
              {CADENCES.map((c) => <th key={c}>{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {categories.map((cat) => (
              <tr key={cat.slug} className="border-t border-slate-100">
                <td className="py-2 text-xs font-medium">{cat.name}</td>
                {CADENCES.map((cadence) => {
                  const id = `${cat.slug}_${cadence}`;
                  const tpl = byId.get(id);
                  return (
                    <td key={cadence} className="py-2">
                      {tpl ? (
                        <span className="flex items-center gap-2">
                          <Link
                            href={`/${locale}/prompts/${id}`}
                            className="text-sky-700 underline"
                          >
                            {id}
                          </Link>
                          <StatusBadge status={tpl.enabled ? 'published' : 'skipped'} />
                        </span>
                      ) : (
                        <Link
                          href={`/${locale}/prompts/${id}`}
                          className="text-xs text-slate-400 underline"
                        >
                          {t('notSeeded')}
                        </Link>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
