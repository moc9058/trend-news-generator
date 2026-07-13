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
