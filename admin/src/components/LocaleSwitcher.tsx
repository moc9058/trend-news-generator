'use client';

import { usePathname, useRouter } from 'next/navigation';

const LOCALES = [
  { code: 'ko', label: '한국어' },
  { code: 'ja', label: '日本語' },
  { code: 'en', label: 'English' },
];

export function LocaleSwitcher({ current }: { current: string }) {
  const pathname = usePathname();
  const router = useRouter();

  function switchTo(locale: string) {
    const rest = pathname.replace(/^\/(ko|ja|en)(?=\/|$)/, '');
    document.cookie = `NEXT_LOCALE=${locale};path=/;max-age=31536000`;
    router.push(`/${locale}${rest}`);
  }

  return (
    <div className="flex gap-1">
      {LOCALES.map((l) => (
        <button
          key={l.code}
          onClick={() => switchTo(l.code)}
          className={`rounded px-2 py-1 text-xs ${
            l.code === current
              ? 'bg-slate-900 text-white'
              : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
          }`}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}
