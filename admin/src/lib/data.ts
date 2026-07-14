/** Server-side Firestore reads for pages (server components only). */

import { db, toIso } from './firestore';
import type {
  AppSettingsDoc, Category, ChannelConfig, ChannelHealth, Claim, EvidenceRecord, Post,
  PromptTemplate, ResearchEvent, ResearchRun, Run, Source,
} from './types';

function mapPost(id: string, data: FirebaseFirestore.DocumentData): Post {
  return {
    id,
    // `?? data.cadence` bridges any not-yet-migrated post doc (see migration §9.2).
    format: data.format ?? data.cadence ?? '',
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
    researchRunId: data.researchRunId ?? '',
    localizations: data.localizations ?? {},
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
    shortRequireApproval: data.shortRequireApproval ?? false,
    xAllowUrlOnShort: data.xAllowUrlOnShort ?? false,
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

/* ---------- Research Agent (report) — direct Firestore reads ---------- */

function mapResearchRun(id: string, data: FirebaseFirestore.DocumentData): ResearchRun {
  return {
    id,
    trigger: data.trigger ?? 'manual',
    requestedBy: data.requestedBy ?? '',
    categoryId: data.categoryId ?? '',
    theme: data.theme ?? '',
    status: data.status ?? '',
    phase: data.phase ?? '',
    loops: data.loops ?? 0,
    budget: data.budget,
    languages: data.languages ?? [],
    canonicalLanguage: data.canonicalLanguage ?? 'ja',
    planApproval: data.planApproval ?? false,
    planApproved: data.planApproved ?? false,
    postId: data.postId ?? '',
    createdAt: toIso(data.createdAt),
    updatedAt: toIso(data.updatedAt),
    plan: data.plan,
  };
}

export async function getResearchRuns(limit = 40): Promise<ResearchRun[]> {
  const snap = await db().collection('researchRuns')
    .orderBy('createdAt', 'desc').limit(limit).get();
  return snap.docs.map((d) => mapResearchRun(d.id, d.data()));
}

export async function getResearchRun(id: string): Promise<ResearchRun | null> {
  const snap = await db().collection('researchRuns').doc(id).get();
  return snap.exists ? mapResearchRun(snap.id, snap.data()!) : null;
}

export async function getResearchEvidence(runId: string): Promise<EvidenceRecord[]> {
  const snap = await db().collection('researchRuns').doc(runId).collection('evidence').get();
  return snap.docs.map((d) => {
    const data = d.data();
    return {
      evidenceId: d.id,
      tier: data.tier ?? '',
      sourceType: data.sourceType ?? '',
      title: data.title ?? '',
      url: data.url ?? '',
      venue: data.venue ?? '',
      publishedAt: data.publishedAt ?? '',
      rqIds: data.rqIds ?? [],
      reliability: data.reliability,
    };
  });
}

export async function getResearchClaims(runId: string): Promise<Claim[]> {
  const snap = await db().collection('researchRuns').doc(runId).collection('claims').get();
  return snap.docs.map((d) => {
    const data = d.data();
    return {
      claimId: d.id,
      rqId: data.rqId ?? '',
      text: data.text ?? '',
      verdict: data.verdict ?? '',
      stance: data.stance ?? '',
      renderAs: data.renderAs ?? '',
      confidence: data.confidence,
      evidenceIds: data.evidenceIds ?? [],
    };
  });
}

export async function getResearchEvents(runId: string, limit = 200): Promise<ResearchEvent[]> {
  const snap = await db().collection('researchRuns').doc(runId).collection('events')
    .orderBy('ts', 'asc').limit(limit).get();
  return snap.docs.map((d) => {
    const data = d.data();
    return {
      id: d.id,
      ts: toIso(data.ts),
      phase: data.phase ?? '',
      actor: data.actor ?? '',
      action: data.action ?? '',
      target: data.target ?? '',
      model: data.model ?? '',
      costUsd: data.costUsd ?? 0,
      ok: data.ok ?? true,
      error: data.error ?? '',
    };
  });
}
