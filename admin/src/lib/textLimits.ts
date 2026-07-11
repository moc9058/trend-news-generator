/** Client-side mirror of pipeline/app/publishers/renderer.py length rules
 * (approximation for live feedback; the pipeline re-validates on publish). */

const URL_RE = /https?:\/\/\S+/g;
const WIDE_RE =
  /[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦　-〿]/;

export function xWeightedLength(text: string): number {
  let total = 0;
  let pos = 0;
  for (const match of text.matchAll(URL_RE)) {
    for (const ch of text.slice(pos, match.index)) total += WIDE_RE.test(ch) ? 2 : 1;
    total += 23;
    pos = (match.index ?? 0) + match[0].length;
  }
  for (const ch of text.slice(pos)) total += WIDE_RE.test(ch) ? 2 : 1;
  return total;
}

export const X_LIMIT = 280;
export const THREADS_LIMIT = 500;
