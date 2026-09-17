/** Check browser code and Node-only tests in their own strict type contexts. */
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const tsc = createRequire(import.meta.url).resolve('typescript/bin/tsc');
const cwd = fileURLToPath(new URL('.', import.meta.url));
for (const project of ['tsconfig.json', 'tsconfig.tests.json']) {
  console.log(`Checking ${project}`);
  const result = spawnSync(process.execPath, [tsc, '--noEmit', '--project', project], { cwd, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
