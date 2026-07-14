import { getTranslations } from 'next-intl/server';
import { btnCls, Card, inputCls, labelCls, PageHeader } from '@/components/ui';
import { savePromptTemplate } from '@/lib/actions';
import { getPromptTemplate } from '@/lib/data';

const areaCls =
  'mt-1 w-full rounded-lg border border-line bg-white p-3 font-mono text-xs leading-relaxed text-ink shadow-card focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/15';

export default async function PromptEditPage({
  params,
}: {
  params: Promise<{ locale: string; id: string }>;
}) {
  const { id } = await params;
  const [t, tc, tpl] = await Promise.all([
    getTranslations('prompts'),
    getTranslations('common'),
    getPromptTemplate(id),
  ]);
  const [categoryId, format] = [
    id.substring(0, id.lastIndexOf('_')),
    id.substring(id.lastIndexOf('_') + 1),
  ];
  const isLongform = format === 'article' || format === 'report';

  return (
    <div>
      <PageHeader title={id} hint={t('placeholders')} />
      <Card>
        <form action={savePromptTemplate} className="space-y-4">
          <input type="hidden" name="id" value={id} />
          <input type="hidden" name="categoryId" value={tpl?.categoryId ?? categoryId} />
          <input type="hidden" name="format" value={tpl?.format ?? format} />
          <label className="block rounded-xl border border-accent-line bg-accent-soft p-4 text-sm">
            <span className="font-semibold text-accent-hover">{t('focusKeywords')}</span>
            <input
              name="focusKeywords"
              className={inputCls}
              defaultValue={(tpl?.focusKeywords ?? []).join(', ')}
              placeholder="AI, semiconductors, monetary policy"
            />
            <span className="mt-1.5 block text-xs leading-relaxed text-slate-500">
              {t('focusKeywordsHint')}
            </span>
          </label>
          <label className="block rounded-xl border border-accent-line bg-accent-soft p-4 text-sm">
            <span className="font-semibold text-accent-hover">{t('customInstructions')}</span>
            <textarea
              name="customInstructions"
              rows={4}
              className={`${inputCls} resize-y leading-relaxed`}
              defaultValue={tpl?.customInstructions ?? ''}
            />
            <span className="mt-1.5 block text-xs leading-relaxed text-slate-500">
              {t('customInstructionsHint')}
            </span>
          </label>
          <label className={labelCls}>
            {t('systemPrompt')}
            <textarea name="systemPrompt" rows={6} className={areaCls}
              defaultValue={tpl?.systemPrompt ?? ''} />
          </label>
          <label className={labelCls}>
            {t('userPrompt')}
            <textarea name="userPromptTemplate" rows={12} className={areaCls}
              defaultValue={tpl?.userPromptTemplate ?? ''} />
          </label>
          {isLongform && (
            <>
              <label className={labelCls}>
                {t('outlineSystemPrompt')}
                <textarea name="outlineSystemPrompt" rows={4} className={areaCls}
                  defaultValue={tpl?.outlineSystemPrompt ?? ''} />
              </label>
              <label className={labelCls}>
                {t('outlineUserPrompt')}
                <textarea name="outlineUserPromptTemplate" rows={8} className={areaCls}
                  defaultValue={tpl?.outlineUserPromptTemplate ?? ''} />
              </label>
            </>
          )}
          <div className="flex max-w-md items-center gap-4">
            <label className={`flex-1 ${labelCls}`}>
              {t('modelOverride')}
              <input name="modelOverride" className={inputCls}
                defaultValue={tpl?.modelOverride ?? ''} />
            </label>
            <label className="flex items-center gap-2 pt-5 text-sm text-slate-600">
              <input
                name="enabled"
                type="checkbox"
                defaultChecked={tpl?.enabled ?? true}
                className="h-4 w-4 rounded border-line"
              />
              {tc('enabled')}
            </label>
          </div>
          <button type="submit" className={btnCls}>{tc('save')}</button>
        </form>
      </Card>
    </div>
  );
}
