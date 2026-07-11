import type { ReactNode } from 'react';
import { NextIntlClientProvider, hasLocale } from 'next-intl';
import { getTranslations } from 'next-intl/server';
import { notFound } from 'next/navigation';
import Link from 'next/link';
import { routing } from '@/i18n/routing';
import { LocaleSwitcher } from '@/components/LocaleSwitcher';
import '../globals.css';

export const dynamic = 'force-dynamic';

const NAV = [
  { href: '', key: 'dashboard' },
  { href: '/drafts', key: 'drafts' },
  { href: '/posts', key: 'posts' },
  { href: '/categories', key: 'categories' },
  { href: '/sources', key: 'sources' },
  { href: '/prompts', key: 'prompts' },
  { href: '/channels', key: 'channels' },
  { href: '/settings', key: 'settings' },
] as const;

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const t = await getTranslations({ locale, namespace: 'nav' });

  return (
    <html lang={locale}>
      <body>
        <NextIntlClientProvider>
          <div className="flex min-h-screen">
            <aside className="w-56 shrink-0 border-r border-slate-200 bg-white p-4">
              <div className="mb-6 text-lg font-bold">Trend News</div>
              <nav className="space-y-1">
                {NAV.map((item) => (
                  <Link
                    key={item.key}
                    href={`/${locale}${item.href}`}
                    className="block rounded px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
                  >
                    {t(item.key)}
                  </Link>
                ))}
              </nav>
              <div className="mt-8">
                <LocaleSwitcher current={locale} />
              </div>
            </aside>
            <main className="flex-1 p-6">{children}</main>
          </div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
