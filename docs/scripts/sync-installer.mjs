import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const docsRoot = resolve(here, '..');
const repoRoot = resolve(docsRoot, '..');
const source = resolve(repoRoot, 'install.sh');

for (const name of ['installer.sh', 'install.sh']) {
  const target = resolve(docsRoot, 'public', name);
  mkdirSync(dirname(target), { recursive: true });
  copyFileSync(source, target);
}
