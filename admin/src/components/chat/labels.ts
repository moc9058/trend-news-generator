import { getTranslations } from 'next-intl/server';
import type { ChatLabels } from './ChatView';
import type { ThreadListLabels } from './ThreadList';

/** ChatView is a client component, so its strings must cross as plain props
 * (the layout resolves nav labels the same way). One list, three call sites. */
const KEYS = [
  'modeChat', 'modeResearch', 'modeChatHint', 'modeResearchHint',
  'depthQuick', 'depthDeep', 'depthQuickHint', 'depthDeepHint',
  'placeholder', 'placeholderResearch', 'send', 'cancel', 'cancelled',
  'sources', 'empty', 'error', 'streaming', 'costLabel',
  'handoff', 'handoffShort', 'handoffArticle', 'handoffReport',
  'handoffCategory', 'handoffTheme', 'handoffSubmit', 'handoffDone',
  'handoffOpenDraft', 'handoffOpenRun', 'handoffNote',
  'statusPlanning', 'statusSearching', 'statusSelecting', 'statusReading',
  'statusGapCheck', 'statusSynthesizing',
] as const;

export async function chatLabels(locale: string): Promise<ChatLabels> {
  const t = await getTranslations({ locale, namespace: 'chat' });
  return Object.fromEntries(KEYS.map((k) => [k, t(k)])) as unknown as ChatLabels;
}

/** Labels for the history rail (a client component), resolved server-side. */
export async function threadListLabels(locale: string): Promise<ThreadListLabels> {
  const t = await getTranslations({ locale, namespace: 'chat' });
  return {
    newChat: t('newChat'),
    noThreads: t('noThreads'),
    noMatches: t('noMatches'),
    untitled: t('untitled'),
    search: t('searchThreads'),
    today: t('groupToday'),
    yesterday: t('groupYesterday'),
    thisWeek: t('groupThisWeek'),
    earlier: t('groupEarlier'),
    rename: t('rename'),
    archive: t('archive'),
    delete: t('delete'),
    confirmDelete: t('confirmDelete'),
    save: t('save'),
    cancel: t('dismiss'),
  };
}
