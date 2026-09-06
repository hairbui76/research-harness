import { execFileSync } from 'node:child_process';
import { chmodSync, existsSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
if (!process.env.CI && existsSync(resolve(root, '.git'))) {
  let existing = '';
  try {
    existing = execFileSync('git', ['config', '--get', 'core.hooksPath'], { cwd: root, encoding: 'utf8' }).trim();
  } catch (error) {
    if (error.status !== 1) throw error;
  }
  if (existing && existing !== '.githooks') {
    throw new Error(`Existing core.hooksPath=${existing}; integrate its hooks before replacing it.`);
  }
  const legacy = execFileSync('git', ['rev-parse', '--git-path', 'hooks'], { cwd: root, encoding: 'utf8' }).trim();
  const directory = resolve(root, legacy);
  const custom = existsSync(directory)
    ? readdirSync(directory, { withFileTypes: true }).filter((entry) => !entry.isDirectory() && !entry.name.endsWith('.sample'))
    : [];
  if (!existing && custom.length > 0) {
    throw new Error(`Existing Git hooks need integration: ${custom.map((entry) => entry.name).join(', ')}. None were disabled.`);
  }
  chmodSync(resolve(root, '.githooks/pre-push'), 0o755);
  execFileSync('git', ['config', '--local', 'core.hooksPath', '.githooks'], { cwd: root });
  console.log('Installed the full pre-push gate for this checkout and its worktrees.');
}
