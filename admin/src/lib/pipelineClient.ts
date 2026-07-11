/** Calls pipeline-api with a Google-signed ID token (Cloud Run service-to-service).
 * Only actions go through here — all reads are direct Firestore. */

import { GoogleAuth } from 'google-auth-library';

const auth = new GoogleAuth();

async function call(path: string, body: unknown): Promise<Response> {
  const base = process.env.PIPELINE_API_URL;
  if (!base) throw new Error('PIPELINE_API_URL is not configured');
  const client = await auth.getIdTokenClient(base);
  const token = await client.idTokenProvider.fetchIdToken(base);
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

export async function runJob(name: string): Promise<{ ok: boolean; detail: string }> {
  const resp = await call(`/api/jobs/${name}/run`, {});
  const text = await resp.text();
  return { ok: resp.ok, detail: text };
}
