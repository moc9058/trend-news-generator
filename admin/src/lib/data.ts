/** Server-side Firestore reads for pages (server components only). */

import { db, toIso } from './firestore';
import type {
  AppSettingsDoc, Category, ChannelConfig, ChannelHealth, Post, PromptTemplate, Run, Source,
} from './types';

function mapPost(id: string, data: FirebaseFirestore.DocumentData): Post {
  return {
    id,
    cadence: data.cadence ?? '',
    categoryId: data.categoryId ?? '',
    status: data.status ?? '',
    title: data.title ?? '',
    summary: data.summary ?? '',
    body: data.body ?? '',
    sourceItemIds: data.sourceItemIds ?? [],
    tokenUsage: data.tokenUsage,
    channels: data.channels ?? {},
    createdAt: toIso(data.createdAt),
    approvedBy: data.approvedBy ?? '',
  };
}

export async function getCategories(): Promise<Category[]> {
  const snap = await db().collection('categories').get();
  return snap.docs
    .map((d) => ({ slug: d.id, ...(d.data() as Omit<Category, 'slug'>) }))
    .sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0));
}

export async function getSources(): Promise<Source[]> {
  const snap = await db().collection('sources').get();
  return snap.docs.map((d) => {
    const data = d.data();
    return {
      id: d.id,
      categoryId: data.categoryId ?? '',
      type: data.type ?? 'rss',
      url: data.url ?? '',
      query: data.query ?? '',
      enabled: data.enabled ?? false,
      lastFetchedAt: toIso(data.lastFetchedAt),
    };
  });
}

export async function getPromptTemplates(): Promise<PromptTemplate[]> {
  const snap = await db().collection('promptTemplates').get();
  return snap.docs.map((d) => ({ id: d.id, ...(d.data() as Omit<PromptTemplate, 'id'>) }));
}

export async function getPromptTemplate(id: string): Promise<PromptTemplate | null> {
  const snap = await db().collection('promptTemplates').doc(id).get();
  return snap.exists ? { id: snap.id, ...(snap.data() as Omit<PromptTemplate, 'id'>) } : null;
}

export async function getChannelConfigs(): Promise<ChannelConfig[]> {
  const snap = await db().collection('channelConfigs').get();
  return snap.docs.map((d) => ({ id: d.id, ...(d.data() as Omit<ChannelConfig, 'id'>) }));
}

export async function getDrafts(): Promise<Post[]> {
  const snap = await db()
    .collection('posts')
    .where('status', '==', 'draft')
    .orderBy('createdAt', 'desc')
    .limit(30)
    .get();
  return snap.docs.map((d) => mapPost(d.id, d.data()));
}

export async function getPost(id: string): Promise<Post | null> {
  const snap = await db().collection('posts').doc(id).get();
  return snap.exists ? mapPost(snap.id, snap.data()!) : null;
}

export async function getRecentPosts(limit = 30): Promise<Post[]> {
  const snap = await db().collection('posts').orderBy('createdAt', 'desc').limit(limit).get();
  return snap.docs.map((d) => mapPost(d.id, d.data()));
}

export async function getRecentRuns(limit = 20): Promise<Run[]> {
  const snap = await db().collection('runs').orderBy('startedAt', 'desc').limit(limit).get();
  return snap.docs.map((d) => {
    const data = d.data();
    return {
      id: d.id,
      jobType: data.jobType ?? '',
      startedAt: toIso(data.startedAt),
      finishedAt: toIso(data.finishedAt),
      ok: data.ok ?? false,
      stats: data.stats,
      errors: data.errors ?? [],
      costUsd: data.costUsd ?? 0,
    };
  });
}

export async function getMonthCostUsd(): Promise<number> {
  const start = new Date();
  start.setUTCDate(1);
  start.setUTCHours(0, 0, 0, 0);
  const snap = await db().collection('runs').where('startedAt', '>=', start).get();
  let total = 0;
  snap.docs.forEach((d) => (total += d.data().costUsd ?? 0));
  return Math.round(total * 100) / 100;
}

export async function getAppSettings(): Promise<AppSettingsDoc> {
  const snap = await db().collection('settings').doc('app').get();
  const data = snap.data() ?? {};
  return {
    timezone: data.timezone ?? 'Asia/Tokyo',
    dailyRequireApproval: data.dailyRequireApproval ?? false,
    xAllowUrlOnDaily: data.xAllowUrlOnDaily ?? false,
    attachImages: data.attachImages ?? true,
  };
}

export async function getNotionDatabaseId(): Promise<string> {
  const snap = await db().collection('settings').doc('notion').get();
  return snap.data()?.databaseId ?? '';
}

export async function getChannelHealth(): Promise<ChannelHealth> {
  const snap = await db().collection('settings').doc('channelHealth').get();
  const data = snap.data() ?? {};
  return {
    threadsTokenExpiresAt: toIso(data.threadsTokenExpiresAt),
    threadsLastRefreshAt: toIso(data.threadsLastRefreshAt),
    threadsRefreshError: data.threadsRefreshError ?? '',
  };
}
