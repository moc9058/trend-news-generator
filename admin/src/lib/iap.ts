import { headers } from 'next/headers';

/** Email of the IAP-authenticated user, for recording who approved a post.
 * Header format: accounts.google.com:user@example.com */
export async function iapUserEmail(): Promise<string> {
  const h = await headers();
  const raw = h.get('x-goog-authenticated-user-email') ?? '';
  return raw.includes(':') ? raw.split(':').pop()! : raw;
}
