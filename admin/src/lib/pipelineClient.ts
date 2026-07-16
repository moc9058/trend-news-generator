/** Calls pipeline-api with a Google-signed ID token (Cloud Run service-to-service).
 * Only actions go through here — all reads are direct Firestore. */

import { GoogleAuth } from 'google-auth-library';

const auth = new GoogleAuth();

export function pipelineBaseUrl(): string {
  const base = process.env.PIPELINE_API_URL;
  if (!base) throw new Error('PIPELINE_API_URL is not configured');
  return base;
}

/** ID token for pipeline-api. Exported so the chat SSE route handler can stream
 * a response through itself rather than buffering it via `call()`. */
export async function getIdToken(audience: string): Promise<string> {
  const client = await auth.getIdTokenClient(audience);
  return client.idTokenProvider.fetchIdToken(audience);
}

async function call(path: string, body: unknown): Promise<Response> {
  const base = pipelineBaseUrl();
  const token = await getIdToken(base);
  return fetch(`${base}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body ?? {}),
  });
}

export async function publishPost(
  postId: string,
  approvedBy: string,
  channels: string[],
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/posts/${postId}/publish`, { approvedBy, channels });
  const text = await resp.text();
  return { ok: resp.ok, detail: text };
}

export async function retryChannel(
  postId: string,
  channel: string,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/posts/${postId}/retry-channel`, { channel });
  const text = await resp.text();
  return { ok: resp.ok, detail: text };
}

export async function deletePost(
  postId: string,
  channels: string[],
  deleteDoc: boolean,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/posts/${postId}/delete`, { channels, deletePost: deleteDoc });
  return { ok: resp.ok, detail: await resp.text() };
}

export async function runJob(name: string): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/jobs/${name}/run`, {});
  const text = await resp.text();
  return { ok: resp.ok, detail: text };
}

/* ---------- Research Agent (report) ---------- */

export async function createResearchRun(
  body: Record<string, unknown>,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call('/api/research/runs', body);
  return { ok: resp.ok, detail: await resp.text() };
}

export async function cancelResearchRun(
  runId: string,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/research/runs/${runId}/cancel`, {});
  return { ok: resp.ok, detail: await resp.text() };
}

export async function approveResearchPlan(
  runId: string,
  approvedBy: string,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/research/runs/${runId}/approve-plan`, { approvedBy });
  return { ok: resp.ok, detail: await resp.text() };
}

/* ---------- Research Chat ---------- */

export async function cancelChatThread(
  threadId: string,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/chat/threads/${threadId}/cancel`, {});
  return { ok: resp.ok, detail: await resp.text() };
}

export async function chatHandoff(
  body: Record<string, unknown>,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call('/api/chat/handoff', body);
  return { ok: resp.ok, detail: await resp.text() };
}

export async function renameChatThread(
  threadId: string,
  title: string,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/chat/threads/${threadId}/rename`, { title });
  return { ok: resp.ok, detail: await resp.text() };
}

export async function archiveChatThread(
  threadId: string,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/chat/threads/${threadId}/archive`, {});
  return { ok: resp.ok, detail: await resp.text() };
}

export async function deleteChatThread(
  threadId: string,
): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/chat/threads/${threadId}/delete`, {});
  return { ok: resp.ok, detail: await resp.text() };
}
