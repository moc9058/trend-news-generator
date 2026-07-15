import type { ReactNode } from 'react';
import { NextIntlClientProvider, hasLocale } from 'next-intl';
import { getTranslations } from 'next-intl/server';
import localFont from 'next/font/local';
import { notFound } from 'next/navigation';
import { routing } from '@/i18n/routing';
import { AppShell } from '@/components/AppShell';
import { type IconName } from '@/components/icons';
import { iapUserEmail } from '@/lib/iap';
import '../globals.css';

/** The one typeface this app ships. Every figure goes through it — costs, IDs,
 * timestamps, reliability scores — because a system that grades things
 * numerically should not render those numbers in an anonymous system mono.
 * IBM Plex was drawn for IBM's technical documentation, which is the register
 * of the material here (government records, papers).
 *
 * Latin-only, 3 weights, 44KB total, vendored rather than fetched from Google
 * at build time: the Docker build should not depend on fonts.gstatic.com.
 * Body text stays on the viewer's own CJK stack — answers follow the user's
 * language (ja/ko/en), so a Latin face would silently fall back exactly where
 * the content is. */
const plexMono = localFont({
  src: [
    { path: '../fonts/IBMPlexMono-400-latin.woff2', weight: '400', style: 'normal' },
    { path: '../fonts/IBMPlexMono-500-latin.woff2', weight: '500', style: 'normal' },
    { path: '../fonts/IBMPlexMono-600-latin.woff2', weight: '600', style: 'normal' },
  ],
  variable: '--font-plex-mono',
  display: 'swap',
  // CJK never reaches this face; keep it out of the way of the system stack.
  fallback: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
});

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
    <html lang={locale} className={plexMono.variable}>
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
