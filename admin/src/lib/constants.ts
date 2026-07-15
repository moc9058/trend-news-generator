import shared from './shared-constants.json';

export const FORMATS = shared.formats;
export const CHANNELS = shared.channels;
export const POST_STATUSES = shared.postStatuses;
export const SOURCE_TYPES = shared.sourceTypes;
export const LANGUAGES = shared.languages;
export const JOB_TYPES = shared.jobTypes;
export const RESEARCH_RUN_STATUSES = shared.researchRunStatuses;
export const CHAT_MODES = shared.chatModes;
export const CHAT_DEPTHS = shared.chatDepths;
export const CHAT_MESSAGE_STATUSES = shared.chatMessageStatuses;

export type Format = (typeof FORMATS)[number];
export type Channel = (typeof CHANNELS)[number];
export type ChatMode = (typeof CHAT_MODES)[number];
export type ChatDepth = (typeof CHAT_DEPTHS)[number];
