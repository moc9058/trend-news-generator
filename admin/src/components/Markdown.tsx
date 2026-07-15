import type { ReactNode } from 'react';

/** Minimal markdown renderer for post bodies (headings, lists, quotes, code
 * fences, bold/italic/code/links). Server-renderable, no dependencies, and no
 * dangerouslySetInnerHTML — inline markup is parsed into React elements. */

const INLINE_RE =
  /(\*\*(?<bold>.+?)\*\*)|(\*(?<italic>[^*]+?)\*)|(`(?<code>[^`]+?)`)|(\[(?<label>[^\]]+)\]\((?<href>[^)\s]+)\))/g;

/** Research chat only: additionally treats a bare `[1]` as a citation marker.
 * The cite alternative MUST stay last — `[1](https://x)` has to match the link
 * alternative first, or the link would be shredded into a citation plus a stray
 * "(https://x)". Post rendering keeps using INLINE_RE and is untouched. */
const INLINE_CITE_RE = new RegExp(
  `${INLINE_RE.source}|(\\[(?<cite>\\d+)\\])`,
  'g',
);

function renderInline(
  text: string,
  cite?: { litN?: number | null; onLit?: (n: number | null) => void },
): ReactNode[] {
  const out: ReactNode[] = [];
  let pos = 0;
  let key = 0;
  for (const m of text.matchAll(cite ? INLINE_CITE_RE : INLINE_RE)) {
    const i = m.index ?? 0;
    if (i > pos) out.push(text.slice(pos, i));
    const g = m.groups ?? {};
    if (g.bold !== undefined) out.push(<strong key={key++}>{g.bold}</strong>);
    else if (g.italic !== undefined) out.push(<em key={key++}>{g.italic}</em>);
    else if (g.code !== undefined)
      out.push(
        <code key={key++} className="rounded bg-paper px-1 py-0.5 font-mono text-[0.85em]">
          {g.code}
        </code>,
      );
    else if (g.label !== undefined)
      out.push(
        <a
          key={key++}
          href={g.href}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-accent underline-offset-2 hover:underline"
        >
          {g.label}
        </a>,
      );
    else if (g.cite !== undefined) {
      const n = Number(g.cite);
      const on = cite?.litN === n;
      out.push(
        <button
          key={key++}
          type="button"
          className={`rounded-sm px-px align-baseline font-mono text-[0.82em] font-medium text-accent ${
            on ? 'bg-accent-soft ring-2 ring-accent-soft' : ''
          } hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent`}
          onMouseEnter={() => cite?.onLit?.(n)}
          onMouseLeave={() => cite?.onLit?.(null)}
          onFocus={() => cite?.onLit?.(n)}
          onBlur={() => cite?.onLit?.(null)}
        >
          [{n}]
        </button>,
      );
    }
    pos = i + m[0].length;
  }
  if (pos < text.length) out.push(text.slice(pos));
  return out;
}

export interface CiteOptions {
  litN?: number | null;
  onLit?: (n: number | null) => void;
}

/** `cite` opts research chat into interactive `[n]` markers. Omit it (posts do)
 * and the parser is byte-for-byte the one that shipped before. */
export function Markdown({ children, cite }: { children: string; cite?: CiteOptions }) {
  const ri = (text: string) => renderInline(text, cite);
  const lines = children.split('\n');
  const blocks: ReactNode[] = [];
  let key = 0;
  let i = 0;
  while (i < lines.length) {
    const stripped = lines[i].trim();
    if (!stripped) {
      i += 1;
      continue;
    }
    if (stripped.startsWith('```')) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // closing fence
      blocks.push(
        <pre
          key={key++}
          className="overflow-x-auto rounded-lg border border-line bg-paper p-3 font-mono text-xs leading-relaxed"
        >
          {code.join('\n')}
        </pre>,
      );
      continue;
    }
    if (['---', '***', '___'].includes(stripped)) {
      blocks.push(<hr key={key++} className="border-line" />);
    } else if (stripped.startsWith('### ')) {
      blocks.push(
        <h3 key={key++} className="text-base font-bold text-ink">
          {ri(stripped.slice(4))}
        </h3>,
      );
    } else if (stripped.startsWith('## ')) {
      blocks.push(
        <h2 key={key++} className="mt-2 border-b border-line pb-1.5 text-lg font-bold text-ink">
          {ri(stripped.slice(3))}
        </h2>,
      );
    } else if (stripped.startsWith('# ')) {
      blocks.push(
        <h1 key={key++} className="text-xl font-bold text-ink">
          {ri(stripped.slice(2))}
        </h1>,
      );
    } else if (stripped.startsWith('> ')) {
      blocks.push(
        <blockquote key={key++} className="border-l-2 border-accent/50 pl-3 text-slate-500">
          {ri(stripped.slice(2))}
        </blockquote>,
      );
    } else if (stripped.startsWith('- ') || stripped.startsWith('* ') || /^\d+\.\s/.test(stripped)) {
      // consecutive list lines → one list
      const ordered = /^\d+\.\s/.test(stripped);
      const items: string[] = [];
      while (i < lines.length) {
        const s = lines[i].trim();
        if (s.startsWith('- ') || s.startsWith('* ')) items.push(s.slice(2));
        else if (/^\d+\.\s/.test(s)) items.push(s.replace(/^\d+\.\s/, ''));
        else break;
        i += 1;
      }
      const cls = 'ml-5 space-y-1';
      blocks.push(
        ordered ? (
          <ol key={key++} className={`${cls} list-decimal`}>
            {items.map((item, n) => (
              <li key={n}>{ri(item)}</li>
            ))}
          </ol>
        ) : (
          <ul key={key++} className={`${cls} list-disc`}>
            {items.map((item, n) => (
              <li key={n}>{ri(item)}</li>
            ))}
          </ul>
        ),
      );
      continue;
    } else {
      blocks.push(
        <p key={key++} className="leading-relaxed">
          {ri(stripped)}
        </p>,
      );
    }
    i += 1;
  }
  return <div className="space-y-3 text-sm text-slate-700">{blocks}</div>;
}
