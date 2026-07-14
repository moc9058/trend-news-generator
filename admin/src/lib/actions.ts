'use server';

/** All mutations: direct Firestore writes for config CRUD; pipeline-api calls
 * for publish / retry / run-now (the actions with side effects beyond the DB). */

import { revalidatePath } from 'next/cache';
import { db } from './firestore';
import { iapUserEmail } from './iap';
import * as pipeline from './pipelineClient';

// ---------- categories ----------

export async function saveCategory(formData: FormData): Promise<void> {
  const slug = String(formData.get('slug') ?? '').trim();
  if (!slug) return;
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
}

export async function toggleCategory(slug: string, enabled: boolean): Promise<void> {
  await db().collection('categories').doc(slug).update({ enabled });
  revalidatePath('/', 'layout');
}

// ---------- sources ----------

export async function saveSource(formData: FormData): Promise<void> {
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

export async function savePromptTemplate(formData: FormData): Promise<void> {
  const id = String(formData.get('id') ?? '');
  if (!id) return;
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
      enabled: formData.get('enabled') === 'on',
    },
    { merge: true },
  );
  revalidatePath('/', 'layout');
}

/** Bulk save for the dashboard's category x format automation grid. */
export async function saveAutomation(formData: FormData): Promise<void> {
  const ids = formData.getAll('ids').map(String);
  const batch = db().batch();
  for (const id of ids) {
    batch.update(db().collection('promptTemplates').doc(id), {
      enabled: formData.get(`enabled_${id}`) === 'on',
    });
  }
  await batch.commit();
  revalidatePath('/', 'layout');
}

// ---------- channel configs ----------

export async function saveChannelConfig(
  id: string, categoryId: string, format: string, channel: string,
  enabled: boolean, language: string,
): Promise<void> {
  await db().collection('channelConfigs').doc(id).set(
    { categoryId, format, channel, enabled, language },
    { merge: true },
  );
  revalidatePath('/', 'layout');
}

// ---------- settings ----------

export async function saveAppSettings(formData: FormData): Promise<void> {
  await db().collection('settings').doc('app').set(
    {
      timezone: String(formData.get('timezone') ?? 'Asia/Tokyo'),
      shortRequireApproval: formData.get('shortRequireApproval') === 'on',
      xAllowUrlOnShort: formData.get('xAllowUrlOnShort') === 'on',
      attachImages: formData.get('attachImages') === 'on',
    },
    { merge: true },
  );
  await db().collection('settings').doc('notion').set(
    { databaseId: String(formData.get('notionDatabaseId') ?? '') },
    { merge: true },
  );
  revalidatePath('/', 'layout');
}

// ---------- drafts ----------

export async function saveDraft(formData: FormData): Promise<void> {
  const id = String(formData.get('id') ?? '');
  if (!id) return;
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

export type ActionResult = { ok: boolean; detail: string };

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

// ---------- research (report) ----------

/** Save a report draft's per-language content. Only title/summary/body are
 * written, via dot-path, so publish-time fields (notionPageId/url) on other
 * languages are never clobbered (design §6.2 / P6). */
export async function saveReportDraft(formData: FormData): Promise<void> {
  const id = String(formData.get('id') ?? '');
  const lang = String(formData.get('lang') ?? '');
  if (!id || !lang) return;
  const updates: Record<string, unknown> = {};
  for (const field of ['title', 'summary', 'body'] as const) {
    const value = formData.get(field);
    if (value !== null) updates[`localizations.${lang}.${field}`] = String(value);
  }
  if (Object.keys(updates).length === 0) return;
  await db().collection('posts').doc(id).update(updates);
  revalidatePath('/', 'layout');
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
