import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { Card, EnabledBadge, PageHeader, Table, tdCls, thCls } from '@/components/ui';
import { FORMATS } from '@/lib/constants';
import { getCategories, getPromptTemplates } from '@/lib/data';

export default async function PromptsPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, tc, templates, categories] = await Promise.all([
    getTranslations('prompts'),
    getTranslations('common'),
    getPromptTemplates(),
    getCategories(),
  ]);
  const byId = new Map(templates.map((tpl) => [tpl.id, tpl]));

  return (
    <div>
      <PageHeader title={t('title')} />
      <Card flush>
        <Table>
          <thead>
            <tr>
              <th className={thCls}></th>
              {FORMATS.map((f) => (
                <th key={f} className={`${thCls} font-mono normal-case`}>{f}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {categories.map((cat) => (
              <tr key={cat.slug} className="transition-colors hover:bg-paper/50">
                <td className={`${tdCls} text-[13px] font-medium text-ink`}>{cat.name}</td>
                {FORMATS.map((fmt) => {
                  const id = `${cat.slug}_${fmt}`;
                  const tpl = byId.get(id);
                  return (
                    <td key={fmt} className={tdCls}>
                      {tpl ? (
                        <span className="inline-flex items-center gap-2">
                          <Link
                            href={`/${locale}/prompts/${id}`}
                            className="font-mono text-xs font-medium text-accent underline-offset-2 hover:underline"
                          >
                            {id}
                          </Link>
                          <EnabledBadge
                            enabled={tpl.enabled}
                            labels={[tc('enabled'), tc('disabled')]}
                          />
                        </span>
                      ) : (
                        <Link
                          href={`/${locale}/prompts/${id}`}
                          className="text-xs text-slate-400 underline underline-offset-2 hover:text-accent"
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
        </Table>
      </Card>
    </div>
  );
}
