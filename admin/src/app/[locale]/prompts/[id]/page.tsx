import { getTranslations } from 'next-intl/server';
import { Card, btnCls, inputCls } from '@/components/ui';
import { savePromptTemplate } from '@/lib/actions';
import { getPromptTemplate } from '@/lib/data';

const areaCls =
  'w-full rounded border border-slate-300 p-2 font-mono text-xs focus:border-slate-500 focus:outline-none';

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
  const [categoryId, cadence] = [
    id.substring(0, id.lastIndexOf('_')),
    id.substring(id.lastIndexOf('_') + 1),
  ];
  const isLongform = cadence === 'weekly' || cadence === 'monthly';

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">{id}</h1>
      <p className="text-xs text-slate-500">{t('placeholders')}</p>
      <Card>
        <form action={savePromptTemplate} className="space-y-3">
          <input type="hidden" name="id" value={id} />
          <input type="hidden" name="categoryId" value={tpl?.categoryId ?? categoryId} />
          <input type="hidden" name="cadence" value={tpl?.cadence ?? cadence} />
          <label className="block rounded border border-sky-200 bg-sky-50 p-3 text-sm">
            <span className="font-medium">{t('focusKeywords')}</span>
            <input name="focusKeywords" className={inputCls}
              defaultValue={(tpl?.focusKeywords ?? []).join(', ')}
              placeholder="AI, semiconductors, monetary policy" />
            <span className="mt-1 block text-xs text-slate-500">{t('focusKeywordsHint')}</span>
          </label>
          <label className="block text-sm">
            {t('systemPrompt')}
            <textarea name="systemPrompt" rows={6} className={areaCls}
              defaultValue={tpl?.systemPrompt ?? ''} />
          </label>
          <label className="block text-sm">
            {t('userPrompt')}
            <textarea name="userPromptTemplate" rows={12} className={areaCls}
              defaultValue={tpl?.userPromptTemplate ?? ''} />
          </label>
          {isLongform && (
            <>
              <label className="block text-sm">
                {t('outlineSystemPrompt')}
                <textarea name="outlineSystemPrompt" rows={4} className={areaCls}
                  defaultValue={tpl?.outlineSystemPrompt ?? ''} />
              </label>
              <label className="block text-sm">
                {t('outlineUserPrompt')}
                <textarea name="outlineUserPromptTemplate" rows={8} className={areaCls}
                  defaultValue={tpl?.outlineUserPromptTemplate ?? ''} />
              </label>
            </>
          )}
          <div className="flex max-w-md items-center gap-4">
            <label className="flex-1 text-sm">
              {t('modelOverride')}
              <input name="modelOverride" className={inputCls}
                defaultValue={tpl?.modelOverride ?? ''} />
            </label>
            <label className="flex items-center gap-2 pt-4 text-sm">
              <input name="enabled" type="checkbox" defaultChecked={tpl?.enabled ?? true} />
              {tc('enabled')}
            </label>
          </div>
          <button type="submit" className={btnCls}>{tc('save')}</button>
        </form>
      </Card>
    </div>
  );
}
