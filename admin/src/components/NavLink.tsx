'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Icon, type IconName } from './icons';

export function NavLink({
  href,
  icon,
  label,
  exact,
}: {
  href: string;
  icon: IconName;
  label: string;
  /** Match only the exact path (for the dashboard root). */
  exact?: boolean;
}) {
  const pathname = usePathname();
  const active = exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      title={label}
      className={`group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
        active
          ? 'bg-ink-raise font-semibold text-white'
          : 'text-ink-muted hover:bg-ink-raise/60 hover:text-white'
      }`}
    >
      {active && (
        <span className="absolute -left-3 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-accent lg:-left-4" />
      )}
      <Icon
        name={icon}
        size={16}
        className={`shrink-0 ${active ? 'text-accent-line' : 'text-ink-faint group-hover:text-ink-muted'}`}
      />
      <span className="hidden truncate lg:block">{label}</span>
    </Link>
  );
}
