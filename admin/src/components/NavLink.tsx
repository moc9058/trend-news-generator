'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icon, type IconName } from './icons';

export function NavLink({
  href,
  icon,
  label,
  exact,
  expanded,
}: {
  href: string;
  icon: IconName;
  label: string;
  /** Match only the exact path (for the dashboard root). */
  exact?: boolean;
  /** Always show the label (mobile drawer), rather than only from lg up. */
  expanded?: boolean;
}) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      title={label}
      className={`group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
        active
          ? 'bg-gradient-to-r from-ink-raise to-ink-raise/50 font-semibold text-white shadow-raised'
          : 'text-ink-muted hover:bg-ink-raise/60 hover:text-white'
      }`}
    >
      {active && (
        <span
          className={`absolute top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-accent ${
            expanded ? '-left-4' : '-left-3 lg:-left-4'
          }`}
        />
      )}
      <Icon
        name={icon}
        size={16}
        className={`shrink-0 ${active ? 'text-accent-line' : 'text-ink-faint group-hover:text-ink-muted'}`}
      />
      <span className={`truncate ${expanded ? 'block' : 'hidden lg:block'}`}>{label}</span>
    </Link>
  );
}
