import type { Config } from 'tailwindcss';

export default {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // "control desk" palette: ink sidebar, warm paper canvas, deep teal accent.
        ink: {
          DEFAULT: '#171B23',
          raise: '#212734',
          line: '#2C3444',
          muted: '#8B94A7',
          faint: '#5C6577',
        },
        paper: '#F4F4F1',
        line: '#E5E4DD',
        accent: {
          DEFAULT: '#0F766E',
          hover: '#0C5E58',
          soft: '#EAF4F2',
          line: '#C7E0DC',
        },
      },
      fontFamily: {
        // IBM Plex Mono (vendored, latin-only) carries every figure in the app.
        // Loaded in [locale]/layout.tsx; the var falls back to the system mono
        // if the face ever fails to load.
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
        card: '0 1px 2px rgb(23 27 35 / 0.04), 0 1px 1px rgb(23 27 35 / 0.03)',
        raised: '0 4px 16px rgb(23 27 35 / 0.08), 0 1px 3px rgb(23 27 35 / 0.05)',
      },
    },
  },
  plugins: [],
} satisfies Config;
