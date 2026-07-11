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
      cadence: String(formData.get('cadence') ?? ''),
      systemPrompt: String(formData.get('systemPrompt') ?? ''),
      userPromptTemplate: String(formData.get('userPromptTemplate') ?? ''),
      outlineSystemPrompt: String(formData.get('outlineSystemPrompt') ?? ''),
      outlineUserPromptTemplate: String(formData.get('outlineUserPromptTemplate') ?? ''),
      modelOverride: String(formData.get('modelOverride') ?? ''),
      enabled: formData.get('enabled') === 'on',
    },
    { merge: true },
  );
  revalidatePath('/', 'layout');
}

// ---------- channel configs ----------

export async function saveChannelConfig(
  id: string, categoryId: string, cadence: string, channel: string,
  enabled: boolean, language: string,
): Promise<void> {
  await db().collection('channelConfigs').doc(id).set(
    { categoryId, cadence, channel, enabled, language },
    { merge: true },
  );
  revalidatePath('/', 'layout');
}

// ---------- settings ----------

export async function saveAppSettings(formData: FormData): Promise<void> {
  await db().collection('settings').doc('app').set(
    {
      timezone: String(formData.get('timezone') ?? 'Asia/Tokyo'),
      dailyRequireApproval: formData.get('dailyRequireApproval') === 'on',
      xAllowUrlOnDaily: formData.get('xAllowUrlOnDaily') === 'on',
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
