// Copies the monorepo-shared constants into src/lib so the admin app builds
// both locally (with ../shared present) and inside its own Docker context
// (where only the committed copy exists). Runs automatically via prebuild.
import { copyFileSync, existsSync } from 'node:fs';

const source = new URL('../../shared/constants.json', import.meta.url);
const target = new URL('../src/lib/shared-constants.json', import.meta.url);

if (existsSync(source)) {
  copyFileSync(source, target);
  console.log('synced shared/constants.json');
} else {
  console.log('shared/constants.json not found; using committed copy');
}
