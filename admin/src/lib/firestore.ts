import { initializeApp, getApps, applicationDefault } from 'firebase-admin/app';
import { getFirestore, Firestore } from 'firebase-admin/firestore';

let cached: Firestore | null = null;

export function db(): Firestore {
  if (cached) return cached;
  const app =
    getApps()[0] ??
    initializeApp({
      credential: applicationDefault(),
      projectId: process.env.PROJECT_ID ?? 'trend-news-generator',
    });
  cached = getFirestore(app);
  return cached;
}

/** Firestore Timestamp | Date | undefined → ISO string for display. */
export function toIso(value: unknown): string {
  if (!value) return '';
  if (value instanceof Date) return value.toISOString();
  const ts = value as { toDate?: () => Date };
  return ts.toDate ? ts.toDate().toISOString() : String(value);
}
