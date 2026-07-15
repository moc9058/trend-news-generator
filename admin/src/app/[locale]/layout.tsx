import type { ReactNode } from 'react';
import { NextIntlClientProvider, hasLocale } from 'next-intl';
import { getTranslations } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { routing } from '@/i18n/routing';
import { AppShell } from '@/components/AppShell';
import { type IconName } from '@/components/icons';
import { iapUserEmail } from '@/lib/iap';
import '../globals.css';

export const dynamic = 'force-dynamic';

/** Slim daily-driver nav. Rarely-used config pages (categories/sources/prompts/
 * channels/research) stay routable but are reached via the settings hub. */
const NAV_GROUPS: { group: string; items: { href: string; key: string; icon: IconName }[] }[] = [
  {
    group: 'groupMain',
    items: [
      { href: '', key: 'dashboard', icon: 'dashboard' },
      { href: '/chat', key: 'chat', icon: 'chat' },
      { href: '/posts', key: 'posts', icon: 'posts' },
      { href: '/drafts', key: 'drafts', icon: 'drafts' },
      { href: '/focus', key: 'focus', icon: 'target' },
    ],
  },
  {
    group: 'groupSystem',
    items: [{ href: '/settings', key: 'settings', icon: 'settings' }],
  },
];

export default async function LocaleLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) notFound();
  const [t, email] = await Promise.all([
    getTranslations({ locale, namespace: 'nav' }),
    iapUserEmail(),
  ]);

  // Resolve translations server-side into serializable props for the client shell.
  const groups = NAV_GROUPS.map(({ group, items }) => ({
    group,
    groupLabel: t(group),
    items: items.map((item) => ({
      href: `/${locale}${item.href}`,
      label: t(item.key),
      icon: item.icon,
      exact: item.href === '',
    })),
  }));

  return (
    <html lang={locale}>
      <body>
        <NextIntlClientProvider>
          <AppShell groups={groups} email={email} locale={locale}>
            {children}
          </AppShell>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
