'use server';

/** All mutations: direct Firestore writes for config CRUD; pipeline-api calls
 * for publish / retry / run-now (the actions with side effects beyond the DB). */

import { revalidatePath } from 'next/cache';
import { db } from './firestore';
import { iapUserEmail } from './iap';
import * as pipeline from './pipelineClient';

export type ActionResult = { ok: boolean; detail: string };

/** Wraps a Firestore-writing action so save forms (via SaveForm) always get
 * an { ok, detail } result instead of an unhandled server-action rejection. */
async function saveResult(run: () => Promise<void>): Promise<ActionResult> {
  try {
    await run();
    return { ok: true, detail: '' };
  } catch (err) {
    return { ok: false, detail: err instanceof Error ? err.message : String(err) };
  }
}

// ---------- categories ----------

export async function saveCategory(formData: FormData): Promise<ActionResult> {
  return saveResult(async () => {
    const slug = String(formData.get('slug') ?? '').trim();
    if (!slug) throw new Error('slug is required');
    await db().collection('categories').doc(slug).set(
      {
        name: String(formData.get('name') ?? slug),
        searchHints: String(formData.get('searchHints') ?? '')
          .split(',').map((s) => s.trim()).filter(Boolean),
        sortOrder: Number(formData.get('sortOrder') ?? 0),
        enabled: formData.get('enabled') === 'on',
      },
      { merge: true },
    );
    revalidatePath('/', 'layout');
  });
}

export async function toggleCategory(slug: string, enabled: boolean): Promise<void> {
  await db().collection('categories').doc(slug).update({ enabled });
  revalidatePath('/', 'layout');
}

// ---------- sources ----------

export async function saveSource(formData: FormData): Promise<ActionResult> {
  return saveResult(async () => {
    const id = String(formData.get('id') ?? '').trim() || `src-${Date.now()}`;
    await db().collection('sources').doc(id).set(
      {
        categoryId: String(formData.get('categoryId') ?? ''),
        type: String(formData.get('type') ?? 'rss'),
        url: String(formData.get('url') ?? ''),
        query: String(formData.get('query') ?? ''),
        enabled: formData.get('enabled') === 'on',
        etag: '',
        lastModified: '',
      },
      { merge: true },
    );
    revalidatePath('/', 'layout');
  });
}

export async function toggleSource(id: string, enabled: boolean): Promise<void> {
  await db().collection('sources').doc(id).update({ enabled });
  revalidatePath('/', 'layout');
}

export async function deleteSource(id: string): Promise<void> {
  await db().collection('sources').doc(id).delete();
  revalidatePath('/', 'layout');
}

// ---------- prompt templates ----------

export async function savePromptTemplate(formData: FormData): Promise<ActionResult> {
  return saveResult(async () => {
    const id = String(formData.get('id') ?? '');
    if (!id) throw new Error('id is required');
    await db().collection('promptTemplates').doc(id).set(
      {
        categoryId: String(formData.get('categoryId') ?? ''),
        format: String(formData.get('format') ?? ''),
        systemPrompt: String(formData.get('systemPrompt') ?? ''),
        userPromptTemplate: String(formData.get('userPromptTemplate') ?? ''),
        outlineSystemPrompt: String(formData.get('outlineSystemPrompt') ?? ''),
        outlineUserPromptTemplate: String(formData.get('outlineUserPromptTemplate') ?? ''),
        modelOverride: String(formData.get('modelOverride') ?? ''),
        focusKeywords: String(formData.get('focusKeywords') ?? '')
          .split(',').map((s) => s.trim()).filter(Boolean),
        customInstructions: String(formData.get('customInstructions') ?? ''),
        enabled: formData.get('enabled') === 'on',
      },
      { merge: true },
    );
    revalidatePath('/', 'layout');
  });
}

/** Focus page: per category x format keywords + free-form owner requests.
 * Merge-only so the (seeded) prompt bodies are never touched. */
export async function saveFocus(formData: FormData): Promise<ActionResult> {
  return saveResult(async () => {
    const id = String(formData.get('id') ?? '');
    if (!id) throw new Error('id is required');
    await db().collection('promptTemplates').doc(id).set(
      {
        focusKeywords: String(formData.get('focusKeywords') ?? '')
          .split(',').map((s) => s.trim()).filter(Boolean),
        customInstructions: String(formData.get('customInstructions') ?? ''),
      },
      { merge: true },
    );
    revalidatePath('/', 'layout');
  });
}

/** Per-channel default languages, used when the automation grid creates a
 * channelConfigs doc that does not exist yet (X=ja / Threads=ko / Notion=en). */
const DEFAULT_CHANNEL_LANGS: Record<string, string> = { x: 'ja', threads: 'ko', notion: 'en' };

/** Bulk save for the dashboard's automation grid: per category x format the
 * generation on/off (promptTemplates.enabled) and per visible channel the
 * channelConfigs on/off. Languages of existing configs are preserved. */
export async function saveAutomation(formData: FormData): Promise<ActionResult> {
  return saveResult(async () => {
    const ids = formData.getAll('ids').map(String);
    const channels = formData.getAll('channels').map(String);
    const existing = new Set(
      (await db().collection('channelConfigs').select().get()).docs.map((d) => d.id),
    );
    const batch = db().batch();
    for (const id of ids) {
      batch.update(db().collection('promptTemplates').doc(id), {
        enabled: formData.get(`enabled_${id}`) === 'on',
      });
      const [categoryId, format] = [id.slice(0, id.lastIndexOf('_')), id.slice(id.lastIndexOf('_') + 1)];
      for (const channel of channels) {
        const cfgId = `${id}_${channel}`;
        const enabled = formData.get(`ch_${id}_${channel}`) === 'on';
        const doc: Record<string, unknown> = { categoryId, format, channel, enabled };
        if (!existing.has(cfgId)) doc.language = DEFAULT_CHANNEL_LANGS[channel] ?? 'en';
        batch.set(db().collection('channelConfigs').doc(cfgId), doc, { merge: true });
      }
    }
    await batch.commit();
    revalidatePath('/', 'layout');
  });
}

// ---------- channel configs ----------

export async function saveChannelConfig(
  id: string, categoryId: string, format: string, channel: string,
  enabled: boolean, language: string,
): Promise<ActionResult> {
  return saveResult(async () => {
    await db().collection('channelConfigs').doc(id).set(
      { categoryId, format, channel, enabled, language },
      { merge: true },
    );
    revalidatePath('/', 'layout');
  });
}

// ---------- settings ----------

export async function saveAppSettings(formData: FormData): Promise<ActionResult> {
  return saveResult(async () => {
    await db().collection('settings').doc('app').set(
      {
        timezone: String(formData.get('timezone') ?? 'Asia/Tokyo'),
        shortRequireApproval: formData.get('shortRequireApproval') === 'on',
        xAllowUrlOnShort: formData.get('xAllowUrlOnShort') === 'on',
        attachImages: formData.get('attachImages') === 'on',
        globalChannels: {
          x: formData.get('channel_x') === 'on',
          threads: formData.get('channel_threads') === 'on',
          notion: formData.get('channel_notion') === 'on',
        },
      },
      { merge: true },
    );
    await db().collection('settings').doc('notion').set(
      { databaseId: String(formData.get('notionDatabaseId') ?? '') },
      { merge: true },
    );
    revalidatePath('/', 'layout');
  });
}

// ---------- drafts ----------

export async function saveDraft(formData: FormData): Promise<ActionResult> {
  return saveResult(async () => {
    const id = String(formData.get('id') ?? '');
    if (!id) throw new Error('id is required');
    const updates: Record<string, unknown> = {
      title: String(formData.get('title') ?? ''),
      summary: String(formData.get('summary') ?? ''),
      body: String(formData.get('body') ?? ''),
    };
    for (const channel of ['x', 'threads'] as const) {
      const text = formData.get(`${channel}Text`);
      if (text !== null) updates[`channels.${channel}.text`] = String(text);
    }
    await db().collection('posts').doc(id).update(updates);
    revalidatePath('/', 'layout');
  });
}

/** Delete a draft. Guarded to status=draft so published posts can never be
 * removed here (they have no delete path). Drafts hold no external artifacts
 * (all channels pending), so a plain Firestore delete is sufficient. */
export async function deleteDraft(postId: string): Promise<void> {
  const snap = await db().collection('posts').doc(postId).get();
  if (snap.exists && snap.data()?.status === 'draft') {
    await db().collection('posts').doc(postId).delete();
  }
  revalidatePath('/', 'layout');
}

export async function approveAndPublish(
  postId: string, channels: string[],
): Promise<ActionResult> {
  const email = await iapUserEmail();
  const result = await pipeline.publishPost(postId, email, channels);
  revalidatePath('/', 'layout');
  return result;
}

export async function retryChannel(postId: string, channel: string): Promise<ActionResult> {
  const result = await pipeline.retryChannel(postId, channel);
  revalidatePath('/', 'layout');
  return result;
}

export async function runJobNow(name: string): Promise<ActionResult> {
  const result = await pipeline.runJob(name);
  revalidatePath('/', 'layout');
  return result;
}

/** Dashboard "report" run button: launches a Research Agent run with automatic
 * theme selection (same as the monthly scheduler, but trigger=manual). */
export async function runReportNow(): Promise<ActionResult> {
  const email = await iapUserEmail();
  const result = await pipeline.createResearchRun({ trigger: 'manual', requestedBy: email });
  revalidatePath('/', 'layout');
  return result;
}

/** Delete selected channels' remote artifacts (X/Threads/Notion) of one post. */
export async function deletePostChannels(
  postId: string, channels: string[],
): Promise<ActionResult> {
  const result = await pipeline.deletePost(postId, channels, false);
  revalidatePath('/', 'layout');
  return result;
}

/** Delete whole posts: remote artifacts on every channel, then the Firestore doc. */
export async function deletePosts(postIds: string[]): Promise<ActionResult> {
  const details: string[] = [];
  let ok = true;
  for (const id of postIds) {
    const result = await pipeline.deletePost(id, [], true);
    if (!result.ok) {
      ok = false;
      details.push(`${id}: ${result.detail}`);
    }
  }
  revalidatePath('/', 'layout');
  return { ok, detail: details.join(' / ') };
}

// ---------- research (report) ----------

/** Save a report draft's per-language content. Only title/summary/body are
 * written, via dot-path, so publish-time fields (notionPageId/url) on other
 * languages are never clobbered (design §6.2 / P6). */
export async function saveReportDraft(formData: FormData): Promise<ActionResult> {
  return saveResult(async () => {
    const id = String(formData.get('id') ?? '');
    const lang = String(formData.get('lang') ?? '');
    if (!id || !lang) throw new Error('id and lang are required');
    const updates: Record<string, unknown> = {};
    for (const field of ['title', 'summary', 'body'] as const) {
      const value = formData.get(field);
      if (value !== null) updates[`localizations.${lang}.${field}`] = String(value);
    }
    if (Object.keys(updates).length === 0) return;
    await db().collection('posts').doc(id).update(updates);
    revalidatePath('/', 'layout');
  });
}

export async function launchResearchRun(formData: FormData): Promise<ActionResult> {
  const email = await iapUserEmail();
  const languages = String(formData.get('languages') ?? 'ja,ko,en')
    .split(',').map((s) => s.trim()).filter(Boolean);
  const result = await pipeline.createResearchRun({
    theme: String(formData.get('theme') ?? ''),
    categoryId: String(formData.get('categoryId') ?? ''),
    budgetUsd: Number(formData.get('budgetUsd') ?? 0),
    planApproval: formData.get('planApproval') === 'on',
    languages,
    canonicalLanguage: String(formData.get('canonicalLanguage') ?? 'ja'),
    requestedBy: email,
    trigger: 'manual',
  });
  revalidatePath('/', 'layout');
  return result;
}

export async function cancelResearchRun(runId: string): Promise<ActionResult> {
  const result = await pipeline.cancelResearchRun(runId);
  revalidatePath('/', 'layout');
  return result;
}

export async function approveResearchPlan(runId: string): Promise<ActionResult> {
  const email = await iapUserEmail();
  const result = await pipeline.approveResearchPlan(runId, email);
  revalidatePath('/', 'layout');
  return result;
}
