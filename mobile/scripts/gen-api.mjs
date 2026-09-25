// Regenerate src/api/schema.d.ts from the backend's OpenAPI spec.
// Usage: npm run gen:api   (needs the backend's Python deps installed)
import { execFileSync, execSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const backend = resolve(root, '../backend');
const python = process.platform === 'win32' ? 'python' : 'python3';

const script = [
  'import json, sys',
  'from app.main import create_app',
  'json.dump(create_app().openapi(), open(sys.argv[1], "w", encoding="utf-8"), indent=1)',
].join('\n');

execFileSync(python, ['-c', script, resolve(root, 'openapi.json')], {
  cwd: backend,
  env: { ...process.env, ENABLE_API_DOCS: 'true' },
  stdio: ['ignore', 'ignore', 'inherit'],
});

execSync('npx --yes openapi-typescript@7 openapi.json -o src/api/schema.d.ts', { cwd: root, stdio: 'inherit' });
