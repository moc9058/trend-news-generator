import Link from 'next/link';
import { getTranslations } from 'next-intl/server';
import { SaveForm } from '@/components/SaveForm';
import { Card, Chip, inputCls, labelCls, PageHeader } from '@/components/ui';
import { saveFocus } from '@/lib/actions';
import { FORMATS } from '@/lib/constants';
import { getCategories, getPromptTemplates } from '@/lib/data';

/** Keywords + free-form owner requests per category x format. Both flow into
 * the generation prompts (pipeline: focusKeywords / customInstructions). */
export default async function FocusPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const [t, tc, tp, categories, templates] = await Promise.all([
    getTranslations('focus'),
    getTranslations('common'),
    getTranslations('prompts'),
    getCategories(),
    getPromptTemplates(),
  ]);
  const templateById = new Map(templates.map((tpl) => [tpl.id, tpl]));

  return (
    <div className="space-y-5">
      <PageHeader title={t('title')} hint={t('hint')} />

      <div className="rounded-xl border border-accent-line bg-accent-soft px-4 py-3 text-sm text-accent">
        {t('multilingualNote')}
      </div>

      {categories.map((cat) => (
        <Card key={cat.slug} title={cat.name}>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {FORMATS.map((fmt) => {
              const id = `${cat.slug}_${fmt}`;
              const tpl = templateById.get(id);
              return (
                <div key={fmt} className="rounded-xl border border-line bg-paper/50 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <Chip>{fmt}</Chip>
                    <Link
                      href={`/${locale}/prompts/${id}`}
                      className="text-[11px] text-slate-400 underline underline-offset-2 hover:text-accent"
                    >
                      {t('advancedEdit')}
                    </Link>
                  </div>
                  {tpl ? (
                    <SaveForm
                      action={saveFocus}
                      saveLabel={tc('save')}
                      savedLabel={tc('saved')}
                      className="space-y-3"
                    >
                      <input type="hidden" name="id" value={id} />
                      <label className={labelCls}>
                        {t('keywords')}
                        <input
                          name="focusKeywords"
                          defaultValue={(tpl.focusKeywords ?? []).join(', ')}
                          placeholder={t('keywordsPlaceholder')}
                          className={inputCls}
                        />
                      </label>
                      <label className={labelCls}>
                        {t('requests')}
                        <textarea
                          name="customInstructions"
                          defaultValue={tpl.customInstructions ?? ''}
                          placeholder={t('requestsPlaceholder')}
                          rows={4}
                          className={`${inputCls} resize-y font-normal leading-relaxed`}
                        />
                      </label>
                    </SaveForm>
                  ) : (
                    <p className="text-xs text-slate-400">{tp('notSeeded')}</p>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      ))}
    </div>
  );
}
