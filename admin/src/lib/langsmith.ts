/**
 * Read-only LangSmith REST client for rendering a research run's trace tree.
 *
 * The pipeline sends traces to LangSmith (US SaaS) whenever the optional
 * `langsmith-api-key` secret exists; this reads them back so the admin UI can
 * show what LangSmith shows — per-call prompts, outputs, latency and nesting —
 * none of which is persisted in Firestore.
 *
 * Same on/off switch as the pipeline: the secret's presence. Deleting it and
 * redeploying removes LANGSMITH_API_KEY here too and the trace card disappears.
 *
 * Raw fetch on purpose — the `langsmith` SDK rides internal ABI (hence the
 * `<1` pin on the Python side) and we only need two read endpoints.
 * Every failure returns null: LangSmith being down must never 500 the page.
 */

const API_URL = process.env.LANGSMITH_ENDPOINT || 'https://api.smith.langchain.com';
const APP_URL = 'https://smith.langchain.com';
const PROJECT = process.env.LANGSMITH_PROJECT || process.env.PROJECT_ID || 'trend-news-generator';

/** Spans past this are dropped — a report run is ~50 spans; 300 is a runaway guard. */
const MAX_SPANS = 300;
/** Prompts/outputs are unbounded; truncate before shipping to the browser. */
const MAX_PAYLOAD_CHARS = 4000;
const TIMEOUT_MS = 8000;

export type TraceSpan = {
  id: string;
  name: string;
  runType: string;
  depth: number;
  startedAt: string;
  durationMs: number | null;
  error: string | null;
  tokensIn: number;
  tokensOut: number;
  costUsd: number;
  inputs: string;
  outputs: string;
  truncated: boolean;
  url: string;
};

export type ResearchTrace = {
  traceId: string;
  url: string;
  spans: TraceSpan[];
  /** True when the trace was cut at MAX_SPANS — the UI says so rather than lying by omission. */
  clipped: boolean;
};

type RawRun = {
  id: string;
  name?: string;
  run_type?: string;
  start_time?: string;
  end_time?: string | null;
  parent_run_id?: string | null;
  trace_id?: string;
  dotted_order?: string;
  error?: string | null;
  inputs?: unknown;
  outputs?: unknown;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_cost?: number | string | null;
  app_path?: string | null;
};

export function langsmithEnabled(): boolean {
  return Boolean(process.env.LANGSMITH_API_KEY);
}

async function ls<T>(path: string, init: RequestInit): Promise<T | null> {
  const key = process.env.LANGSMITH_API_KEY;
  if (!key) return null;
  try {
    const res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { 'X-Api-Key': key, 'Content-Type': 'application/json', ...init.headers },
      signal: AbortSignal.timeout(TIMEOUT_MS),
      cache: 'no-store',
    });
    if (!res.ok) {
      console.warn(`langsmith ${path} -> ${res.status}`);
      return null;
    }
    return (await res.json()) as T;
  } catch (err) {
    console.warn(`langsmith ${path} failed`, err);
    return null;
  }
}

let projectId: string | null = null;

/** LangSmith's /runs/query wants a session UUID, not a project name. */
async function getProjectId(): Promise<string | null> {
  if (projectId) return projectId;
  const rows = await ls<Array<{ id: string }>>(
    `/sessions?name=${encodeURIComponent(PROJECT)}&limit=1`,
    { method: 'GET' },
  );
  projectId = rows?.[0]?.id ?? null;
  return projectId;
}

/**
 * Cursor-paginate /runs/query up to `cap` runs.
 *
 * `more` distinguishes "that was everything" from "we stopped at the cap" — the
 * caller has to tell the user which, so it cannot be inferred from length alone.
 * A short page is the end-of-results signal; the API keeps handing back a
 * `cursors.next` regardless, so trusting that alone would loop past the end.
 */
async function queryRuns(
  body: Record<string, unknown>,
  cap: number,
): Promise<{ runs: RawRun[]; more: boolean }> {
  const pageSize = Math.min(cap, 100);
  const out: RawRun[] = [];
  let cursor: string | undefined;
  let more = false;

  for (;;) {
    const page = await ls<{ runs?: RawRun[]; cursors?: { next?: string } }>('/runs/query', {
      method: 'POST',
      body: JSON.stringify({ ...body, limit: pageSize, ...(cursor ? { cursor } : {}) }),
    });
    if (!page?.runs?.length) break;
    out.push(...page.runs);
    if (page.runs.length < pageSize) break;
    if (out.length >= cap) {
      more = true;
      break;
    }
    cursor = page.cursors?.next;
    if (!cursor) break;
  }

  return { runs: out.slice(0, cap), more };
}

function render(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const SPAN_SELECT = [
  'id', 'name', 'run_type', 'start_time', 'end_time', 'parent_run_id', 'trace_id',
  'dotted_order', 'error', 'inputs', 'outputs', 'prompt_tokens', 'completion_tokens',
  'total_cost', 'app_path',
];

/**
 * Fetch the LangSmith trace for a research run. Null when tracing is off, the
 * run predates tracing, or LangSmith is unreachable — all indistinguishable to
 * the caller on purpose, since the UI treats them the same (hide the card).
 */
export async function getResearchTrace(runId: string): Promise<ResearchTrace | null> {
  const session = await getProjectId();
  if (!session) return null;

  // runner.py stamps metadata.runId on the graph config; the root run is also
  // named `research:{runId}`, but metadata survives a rename.
  const { runs: roots } = await queryRuns({
    session: [session],
    filter: `and(eq(metadata_key, "runId"), eq(metadata_value, "${runId}"))`,
    is_root: true,
    select: ['id', 'trace_id'],
  }, 1);
  const traceId = roots[0]?.trace_id;
  if (!traceId) return null;

  const { runs, more: clipped } = await queryRuns({
    session: [session],
    trace: traceId,
    select: SPAN_SELECT,
  }, MAX_SPANS);
  if (!runs.length) return null;

  // dotted_order encodes {time}{uuid} per ancestor joined by dots, so a plain
  // lexical sort yields exactly the parent-before-child, chronological order.
  const ordered = [...runs]
    .sort((a, b) => (a.dotted_order ?? '').localeCompare(b.dotted_order ?? ''));

  const depths = new Map<string, number>();
  const spans: TraceSpan[] = ordered.map((r) => {
    const depth = r.parent_run_id ? (depths.get(r.parent_run_id) ?? 0) + 1 : 0;
    depths.set(r.id, depth);

    const inputs = render(r.inputs);
    const outputs = render(r.outputs);
    const started = r.start_time ? Date.parse(r.start_time) : NaN;
    const ended = r.end_time ? Date.parse(r.end_time) : NaN;

    return {
      id: r.id,
      name: r.name ?? '',
      runType: r.run_type ?? '',
      depth,
      startedAt: r.start_time ?? '',
      durationMs: Number.isNaN(started) || Number.isNaN(ended) ? null : ended - started,
      error: r.error ?? null,
      tokensIn: r.prompt_tokens ?? 0,
      tokensOut: r.completion_tokens ?? 0,
      costUsd: Number(r.total_cost ?? 0),
      inputs: inputs.slice(0, MAX_PAYLOAD_CHARS),
      outputs: outputs.slice(0, MAX_PAYLOAD_CHARS),
      truncated: inputs.length > MAX_PAYLOAD_CHARS || outputs.length > MAX_PAYLOAD_CHARS,
      url: r.app_path ? `${APP_URL}${r.app_path}` : '',
    };
  });

  return { traceId, url: spans[0]?.url ?? '', spans, clipped };
}
