'use client';

import { usePathname, useRouter } from 'next/navigation';

const LOCALES = [
  { code: 'ko', label: '한국어', short: 'KO' },
  { code: 'ja', label: '日本語', short: 'JA' },
  { code: 'en', label: 'English', short: 'EN' },
];

export function LocaleSwitcher({ current, expanded }: { current: string; expanded?: boolean }) {
  const pathname = usePathname();
  const router = useRouter();

  function switchTo(locale: string) {
    const rest = pathname.replace(/^\/(ko|ja|en)(?=\/|$)/, '');
    document.cookie = `NEXT_LOCALE=${locale};path=/;max-age=31536000`;
    router.push(`/${locale}${rest}`);
  }

  return (
    <div
      className={`flex gap-1 rounded-lg bg-ink-raise/60 p-1 ${
        expanded ? 'flex-row' : 'flex-col lg:flex-row'
      }`}
    >
      {LOCALES.map((l) => (
        <button
          key={l.code}
          onClick={() => switchTo(l.code)}
          title={l.label}
          className={`flex-1 rounded-md px-2 py-1 font-mono text-[11px] font-semibold tracking-wide transition-colors ${
            l.code === current
              ? 'bg-white text-ink shadow-card'
              : 'text-ink-muted hover:text-white'
          }`}
        >
          <span className={expanded ? 'hidden' : 'lg:hidden'}>{l.short}</span>
          <span className={expanded ? 'inline' : 'hidden lg:inline'}>{l.label}</span>
        </button>
      ))}
    </div>
  );
}
