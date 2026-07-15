/** SSE bridge to pipeline-api's chat endpoint — this repo's only route handler.
 *
 * Everything else in admin either reads Firestore directly or POSTs an action
 * through a server action. Neither works here: a server action cannot return a
 * live stream, so the browser needs a URL it can fetch and read incrementally.
 *
 * This handler adds what the browser cannot: the IAP identity and the Google ID
 * token for pipeline-api. The response body is piped through untouched — parsing
 * or re-encoding it here would buffer the stream and defeat the point.
 *
 * `src/middleware.ts` excludes /api from the i18n matcher, so this path is not
 * locale-prefixed.
 */

import { iapUserEmail } from '@/lib/iap';
import { getIdToken, pipelineBaseUrl } from '@/lib/pipelineClient';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
// Streaming a deep research run can take ~10 minutes; pipeline-api's own
// wall-clock guard is the real limit.
export const maxDuration = 900;

export async function POST(req: Request): Promise<Response> {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: 'invalid JSON body' }, { status: 400 });
  }

  const base = pipelineBaseUrl();
  const token = await getIdToken(base);
  // requestedBy comes from the IAP header, never from the client.
  const payload = { ...body, requestedBy: await iapUserEmail() };

  const upstream = await fetch(`${base}/api/chat/messages`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(payload),
    signal: req.signal,
  });

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => '');
    return Response.json(
      { error: detail || `pipeline-api returned ${upstream.status}` },
      { status: upstream.status },
    );
  }

  return new Response(upstream.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}
