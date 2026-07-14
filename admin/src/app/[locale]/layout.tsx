import type { ReactNode } from 'react';
import { NextIntlClientProvider, hasLocale } from 'next-intl';
import { getTranslations } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { routing } from '@/i18n/routing';
import { LocaleSwitcher } from '@/components/LocaleSwitcher';
import { NavLink } from '@/components/NavLink';
import { Icon, type IconName } from '@/components/icons';
import { iapUserEmail } from '@/lib/iap';
import '../globals.css';

export const dynamic = 'force-dynamic';

/** Nav grouped by the pipeline's actual flow: monitor → content → pipeline config → system. */
const NAV_GROUPS: { group: string; items: { href: string; key: string; icon: IconName }[] }[] = [
  {
    group: 'groupMonitor',
    items: [{ href: '', key: 'dashboard', icon: 'dashboard' }],
  },
  {
    group: 'groupContent',
    items: [
      { href: '/drafts', key: 'drafts', icon: 'drafts' },
      { href: '/posts', key: 'posts', icon: 'posts' },
      { href: '/research', key: 'research', icon: 'research' },
    ],
  },
  {
    group: 'groupPipeline',
    items: [
      { href: '/categories', key: 'categories', icon: 'categories' },
      { href: '/sources', key: 'sources', icon: 'sources' },
      { href: '/prompts', key: 'prompts', icon: 'prompts' },
      { href: '/channels', key: 'channels', icon: 'channels' },
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

  return (
    <html lang={locale}>
      <body>
        <NextIntlClientProvider>
          <div className="flex min-h-screen">
            <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col bg-ink px-3 py-5 lg:w-64 lg:px-4">
              <div className="mb-8 flex items-center gap-3 px-1">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent font-mono text-sm font-bold text-white">
                  T
                </div>
                <div className="hidden leading-tight lg:block">
                  <div className="text-sm font-bold tracking-tight text-white">Trend News</div>
                  <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-ink-faint">
                    Control Desk
                  </div>
                </div>
              </div>

              <nav className="flex-1 space-y-5 overflow-y-auto">
                {NAV_GROUPS.map(({ group, items }) => (
                  <div key={group}>
                    <div className="mb-1.5 hidden px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-faint lg:block">
                      {t(group)}
                    </div>
                    <div className="space-y-0.5">
                      {items.map((item) => (
                        <NavLink
                          key={item.key}
                          href={`/${locale}${item.href}`}
                          icon={item.icon}
                          label={t(item.key)}
                          exact={item.href === ''}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </nav>

              <div className="mt-6 space-y-3">
                {email && (
                  <div
                    className="flex items-center gap-2 px-1 text-ink-muted"
                    title={email}
                  >
                    <Icon name="user" size={14} className="shrink-0 text-ink-faint" />
                    <span className="hidden truncate font-mono text-[11px] lg:block">{email}</span>
                  </div>
                )}
                <LocaleSwitcher current={locale} />
              </div>
            </aside>

            <main className="min-w-0 flex-1">
              <div className="mx-auto max-w-6xl px-5 py-8 lg:px-10">{children}</div>
            </main>
          </div>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
