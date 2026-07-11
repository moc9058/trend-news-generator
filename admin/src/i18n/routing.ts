import { defineRouting } from 'next-intl/routing';

export const routing = defineRouting({
  locales: ['ko', 'ja', 'en'],
  defaultLocale: 'ko',
  localeDetection: false,
});
