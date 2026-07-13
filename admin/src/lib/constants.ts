import shared from './shared-constants.json';

export const FORMATS = shared.formats;
export const CHANNELS = shared.channels;
export const POST_STATUSES = shared.postStatuses;
export const SOURCE_TYPES = shared.sourceTypes;
export const LANGUAGES = shared.languages;
export const JOB_TYPES = shared.jobTypes;
export const RESEARCH_RUN_STATUSES = shared.researchRunStatuses;

export type Format = (typeof FORMATS)[number];
export type Channel = (typeof CHANNELS)[number];
