export interface ChannelState {
  enabled: boolean;
  lang: string;
  text: string;
  threadParts?: string[];
  status: string;
  externalId?: string;
  url?: string;
  error?: string;
  imageGcsPath?: string;
  containerId?: string;
  pageId?: string;
}

export interface LocalizedContent {
  title: string;
  summary: string;
  body: string;
  notionPageId?: string;
  url?: string;
}

export interface Post {
  id: string;
  format: string;
  categoryId: string;
  status: string;
  title: string;
  summary: string;
  body: string;
  sourceItemIds: string[];
  tokenUsage?: { inputTokens: number; outputTokens: number; costUsd: number };
  channels: Record<string, ChannelState>;
  createdAt: string;
  approvedBy?: string;
  // report format only
  researchRunId?: string;
  localizations?: Record<string, LocalizedContent>;
}

export interface Category {
  slug: string;
  name: string;
  searchHints: string[];
  enabled: boolean;
  sortOrder: number;
}

export interface Source {
  id: string;
  categoryId: string;
  type: string;
  url: string;
  query: string;
  enabled: boolean;
  lastFetchedAt?: string;
}

export interface PromptTemplate {
  id: string;
  categoryId: string;
  format: string;
  systemPrompt: string;
  userPromptTemplate: string;
  outlineSystemPrompt?: string;
  outlineUserPromptTemplate?: string;
  modelOverride?: string;
  focusKeywords?: string[];
  enabled: boolean;
}

export interface ChannelConfig {
  id: string;
  categoryId: string;
  format: string;
  channel: string;
  enabled: boolean;
  language: string;
}

export interface Run {
  id: string;
  jobType: string;
  startedAt: string;
  finishedAt?: string;
  ok: boolean;
  stats?: Record<string, number>;
  errors?: string[];
  costUsd?: number;
}

export interface AppSettingsDoc {
  timezone: string;
  shortRequireApproval: boolean;
  xAllowUrlOnShort: boolean;
  attachImages: boolean;
}

export interface ChannelHealth {
  threadsTokenExpiresAt?: string;
  threadsLastRefreshAt?: string;
  threadsRefreshError?: string;
}

/* ---------- Research Agent (report) ---------- */

export interface ResearchQuestion {
  id: string;
  q: string;
  strategies: string[];
  resolved: boolean;
}

export interface ResearchRun {
  id: string;
  trigger: string;
  requestedBy: string;
  categoryId: string;
  theme: string;
  status: string;
  phase: string;
  loops: number;
  budget?: {
    usdCap: number;
    usdSpent: number;
    fetchCap: number;
    fetchUsed: number;
    drCallsUsed: number;
  };
  languages: string[];
  canonicalLanguage: string;
  planApproval: boolean;
  planApproved?: boolean;
  postId?: string;
  createdAt: string;
  updatedAt?: string;
  plan?: { themeClass: string; contested: boolean; rqs: ResearchQuestion[] };
}

export interface EvidenceRecord {
  evidenceId: string;
  tier: string;
  sourceType: string;
  title: string;
  url: string;
  venue?: string;
  publishedAt?: string;
  rqIds?: string[];
  reliability?: { score: number; rationale?: string };
}

export interface Claim {
  claimId: string;
  rqId: string;
  text: string;
  verdict: string;
  stance?: string;
  renderAs?: string;
  confidence?: number;
  evidenceIds?: string[];
}

export interface ResearchEvent {
  id: string;
  ts: string;
  phase: string;
  actor: string;
  action: string;
  target?: string;
  model?: string;
  costUsd?: number;
  ok: boolean;
  error?: string;
}
