import type { Config } from 'tailwindcss';

/** Colour that respects Tailwind opacity utilities (`bg-x/60`). The CSS var
 *  holds space-separated RGB channels (see globals.css `:root`). */
const v = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  // Dark-only today. Kept explicit so a future light theme can be a class toggle.
  darkMode: 'class',
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // "Midnight Indigo" — values live as CSS vars in globals.css.
        bg: v('--bg'),
        surface: {
          DEFAULT: v('--surface'),
          2: v('--surface-2'),
          3: v('--surface-3'),
        },
        fg: {
          DEFAULT: v('--fg'),
          muted: v('--fg-muted'),
          faint: v('--fg-faint'),
        },
        // `line` repointed to the hairline border — every existing `border-line`
        // usage tracks the dark palette with no edit.
        line: v('--border'),
        // `paper` repointed to the raised fill — remaining `bg-paper/xx` usages
        // become correct subtle-raised surfaces on dark (the body canvas moved to
        // `bg-bg` in globals.css).
        paper: v('--surface-2'),
        // `ink` stays the darkest surface family for the sidebar/rail. Text that
        // used `text-ink` is migrated to `text-fg` (near-black text is invisible
        // on a dark canvas); `bg-ink`/`from-ink` keep meaning the rail surface.
        ink: {
          DEFAULT: '#0C0F1E',
          raise: '#181D3D',
          line: '#262B4A',
          muted: '#99A0C0',
          faint: '#6B7099',
        },
        accent: {
          DEFAULT: v('--accent'),
          hover: v('--accent-hover'),
          contrast: v('--accent-contrast'),
          soft: v('--accent-soft'),
          line: v('--accent-line'),
        },
      },
      fontFamily: {
        // IBM Plex Mono (vendored, latin-only) carries every figure in the app.
        // Loaded in [locale]/layout.tsx; falls back to the system mono.
        mono: [
          'var(--font-plex-mono)',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          'monospace',
        ],
      },
      boxShadow: {
        // On dark, elevation reads as a hairline ring + a soft low drop, plus a
        // 1px inner top-highlight so a raised surface catches a little light.
        card: '0 0 0 1px rgb(0 0 0 / 0.20), 0 1px 2px rgb(0 0 0 / 0.40), inset 0 1px 0 rgb(255 255 255 / 0.03)',
        raised:
          '0 0 0 1px rgb(0 0 0 / 0.25), 0 14px 34px -10px rgb(0 0 0 / 0.65), inset 0 1px 0 rgb(255 255 255 / 0.04)',
      },
      keyframes: {
        caret: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        caret: 'caret 1.05s step-end infinite',
        shimmer: 'shimmer 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
} satisfies Config;
