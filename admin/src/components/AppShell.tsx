'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import { LocaleSwitcher } from './LocaleSwitcher';
import { NavLink } from './NavLink';
import { Icon, type IconName } from './icons';

export type NavItem = { href: string; label: string; icon: IconName; exact: boolean };
export type NavGroup = { group: string; groupLabel: string; items: NavItem[] };

/** Brand lockup. `compact` hides the wordmark until lg (desktop rail collapses to the mark). */
function Brand({ compact }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3 px-1">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-teal-500 to-accent-hover font-mono text-sm font-bold text-white shadow-raised">
        T
      </div>
      <div className={compact ? 'hidden leading-tight lg:block' : 'leading-tight'}>
        <div className="text-sm font-bold tracking-tight text-white">Trend News</div>
        <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-ink-faint">
          Control Desk
        </div>
      </div>
    </div>
  );
}

/** The nav body is shared by the desktop rail and the mobile drawer; `expanded`
 *  forces labels/group headers/email visible even below lg (drawer is full-width). */
function NavBody({
  groups,
  email,
  locale,
  expanded,
}: {
  groups: NavGroup[];
  email: string | null;
  locale: string;
  expanded?: boolean;
}) {
  return (
    <>
      <nav className="flex-1 space-y-5 overflow-y-auto">
        {groups.map(({ group, groupLabel, items }) => (
          <div key={group}>
            <div
              className={`mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-faint ${
                expanded ? 'block' : 'hidden lg:block'
              }`}
            >
              {groupLabel}
            </div>
            <div className="space-y-0.5">
              {items.map((item) => (
                <NavLink
                  key={item.href}
                  href={item.href}
                  icon={item.icon}
                  label={item.label}
                  exact={item.exact}
                  expanded={expanded}
                />
              ))}
            </div>
          </div>
        ))}
      </nav>

      <div className="mt-6 space-y-3">
        {email && (
          <div className="flex items-center gap-2 px-1 text-ink-muted" title={email}>
            <Icon name="user" size={14} className="shrink-0 text-ink-faint" />
            <span className={`truncate font-mono text-[11px] ${expanded ? 'block' : 'hidden lg:block'}`}>
              {email}
            </span>
          </div>
        )}
        <LocaleSwitcher current={locale} expanded={expanded} />
      </div>
    </>
  );
}

export function AppShell({
  groups,
  email,
  locale,
  children,
}: {
  groups: NavGroup[];
  email: string | null;
  locale: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // Close the drawer whenever the route changes (tap a link → navigate → close).
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // While the drawer is open, lock body scroll and allow Esc to close it.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open]);

  return (
    <div className="flex min-h-screen">
      {/* Desktop rail (lg+): icon-only at lg, full at lg width, exactly as before. */}
      <aside className="sticky top-0 hidden h-screen w-16 shrink-0 flex-col border-r border-white/5 bg-gradient-to-b from-ink to-[#10141C] px-3 py-5 lg:flex lg:w-64 lg:px-4">
        <div className="mb-8">
          <Brand compact />
        </div>
        <NavBody groups={groups} email={email} locale={locale} />
      </aside>

      {/* Mobile off-canvas drawer + backdrop (below lg). */}
      <div className={`lg:hidden ${open ? '' : 'pointer-events-none'}`}>
        <div
          className={`fixed inset-0 z-40 bg-ink/50 backdrop-blur-sm transition-opacity duration-200 ${
            open ? 'opacity-100' : 'opacity-0'
          }`}
          onClick={() => setOpen(false)}
          aria-hidden
        />
        <aside
          className={`fixed inset-y-0 left-0 z-50 flex w-72 max-w-[82vw] flex-col bg-gradient-to-b from-ink to-[#10141C] px-4 py-5 shadow-2xl transition-transform duration-200 ease-out ${
            open ? 'translate-x-0' : '-translate-x-full'
          }`}
          role="dialog"
          aria-modal="true"
          aria-hidden={!open}
        >
          <div className="mb-8 flex items-center justify-between">
            <Brand />
            <button
              onClick={() => setOpen(false)}
              className="rounded-lg p-1.5 text-ink-muted transition-colors hover:bg-ink-raise hover:text-white"
              aria-label="Close menu"
            >
              <Icon name="close" size={18} />
            </button>
          </div>
          <NavBody groups={groups} email={email} locale={locale} expanded />
        </aside>
      </div>

      {/* Content column with a mobile-only top bar carrying the menu trigger. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-white/90 px-4 py-2.5 backdrop-blur lg:hidden">
          <button
            onClick={() => setOpen(true)}
            className="rounded-lg p-1.5 text-slate-600 transition-colors hover:bg-paper"
            aria-label="Open menu"
          >
            <Icon name="menu" size={20} />
          </button>
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent font-mono text-xs font-bold text-white">
              T
            </div>
            <span className="text-sm font-bold tracking-tight text-ink">Trend News</span>
          </div>
        </header>

        <main className="min-w-0 flex-1">
          <div className="mx-auto max-w-6xl px-4 py-6 sm:px-5 lg:px-10 lg:py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
