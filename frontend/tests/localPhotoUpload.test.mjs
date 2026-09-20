import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';
import { webcrypto } from 'node:crypto';

const ts = createRequire(import.meta.url)('typescript');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const clone = value => JSON.parse(JSON.stringify(value));
const cache = new Map();
function load(path) {
  path = resolve(path); if (!existsSync(path)) path += '.ts';
  if (cache.has(path)) return cache.get(path);
  const exports = {}; cache.set(path, exports);
  const js = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  runInNewContext(js, { exports, require: name => load(resolve(dirname(path), name)), Blob, File, Uint8Array, TextEncoder, TextDecoder,
    AbortController, setTimeout, clearTimeout, crypto: webcrypto, Error, process: { env: {} } });
  return exports;
}
const { LocalPhotoUpload, describeLocalFiles, readLocalImport, LOCAL_PHOTO_LIMIT } = load(root + '/lib/localPhotoUpload.ts');
const { photoOriginalNotice, photoSourceLabel, confirmPhotos } = load(root + '/lib/photos.ts');
const batch = 'a'.repeat(24), slot = i => String(i + 1).padStart(24, '0');
const file = (name = '合成照片.jpg', bytes = 'synthetic-file', type = 'image/jpeg') => new File([bytes], name, { type, lastModified: 0 });
const gate = () => { let release; const promise = new Promise(resolve => { release = resolve; }); return { promise, release }; };
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

// Real controller, hashing, identity fence, request body and response stream.
// Transport/DTOs are synthetic: this is not backend, decoder or browser E2E.
function fixture() {
  const f = { me: { user: { id: 'member1', role: 'member', householdId: 'home', auth_version: 1 }, csrf: 'synthetic' },
    current: true, denied: 0, reviewed: [], calls: [], detail: null, hook: null };
  f.transport = async (path, init) => {
    f.calls.push({ path, ...init });
    if (f.hook) { const response = await f.hook(path, init); if (response) return response; }
    if (path === '/api/me') return json(f.me);
    if (path === '/api/media/local-imports') {
      const body = JSON.parse(init.body);
      if (!f.detail) f.detail = { import: { source: 'local-upload', id: batch, revision: 1, state: 'staging', createdAt: '2026-09-20', expiresAt: '2026-09-21', canConfirm: false, resultsState: 'known', results: [],
        counts: { selected: body.files.length, ready: 0, failed: 0, pending: body.files.length, saved: 0, skipped: 0, unselected: 0 } }, items: [], upload: { canUpload: true, files: body.files.map((d, i) => ({ ...d, slotId: slot(i), status: 'pending' })) } };
      if (f.loseCreate) { f.loseCreate = false; throw new Error('synthetic dropped response'); }
      return json(f.detail, 201);
    }
    if (path === '/api/media/imports/' + batch) return json(f.detail);
    if (init.method === 'PUT') {
      const target = f.detail.upload.files.find(s => path.endsWith('/' + s.slotId));
      assert.ok(target); assert.equal(init.body instanceof File, true);
      assert.equal(init.headers['X-Import-Revision'], String(f.detail.import.revision));
      assert.equal(init.headers['Content-Type'], target.contentType);
      assert.equal(init.headers['X-CSRF-Token'], 'synthetic');
      assert.equal(await init.body.text(), target.filename.includes('second') ? 'second' : 'synthetic-file');
      target.status = f.slotStatus || 'successful'; ++f.detail.import.revision;
      f.detail.import.counts.pending--; f.detail.import.counts.ready++;
      if (f.afterPut) await f.afterPut();
      if (f.losePut) { f.losePut = false; throw new Error('synthetic dropped response'); }
      return json(f.detail);
    }
    if (path.endsWith('/finish')) {
      if (f.finishConflict) { f.finishConflict = false; f.detail.import.revision++; return json({ code: 'conflict' }, 409); }
      const body = JSON.parse(init.body);
      if (!f.finished) { assert.equal(body.revision, f.detail.import.revision); f.finished = body; ++f.detail.import.revision;
        f.detail.upload.files.filter(s => s.status === 'pending').forEach(s => { s.status = 'skipped'; });
        f.detail.import.state = f.detail.import.counts.ready ? 'awaiting_confirmation' : 'failed';
        f.detail.import.canConfirm = !!f.detail.import.counts.ready; f.detail.upload.canUpload = false;
        if (!f.detail.import.canConfirm) f.detail.upload.files = []; }
      if (f.loseFinish) { f.loseFinish = false; throw new Error('synthetic dropped response'); }
      return json(f.detail);
    }
    throw new Error('unexpected ' + path);
  };
  f.make = () => new LocalPhotoUpload({ user: clone(f.me.user), current: () => f.current, denied: () => f.denied++, review: async id => f.reviewed.push(id), transport: f.transport });
  f.controller = f.make(); f.writes = method => f.calls.filter(c => c.method !== 'GET' && (!method || c.method === method));
  return f;
}

test('all declarations are validated before any bytes; count/size/MIME/basename bounds', async () => {
  for (const files of [Array.from({ length: 11 }, () => file()), [file('../secret.jpg')], [file('x.heic', 'x', 'image/heic')], [file('x.mp4', 'x', 'video/mp4')], [file('x.jpg', '')], [file('x.jpg', new Uint8Array(LOCAL_PHOTO_LIMIT + 1))]]) {
    let reads = 0; files[0].arrayBuffer = async () => { reads++; return new ArrayBuffer(1); };
    await assert.rejects(describeLocalFiles(files, () => true)); assert.equal(reads, 0);
  }
});
test('source SHA/type/size are exact; dates and filesystem paths are not submitted', async () => {
  const fs = ['image/jpeg', 'image/png', 'image/webp'].map((type, i) => file('safe' + i, 'synthetic-file', type));
  const rows = await describeLocalFiles(fs, () => true);
  assert.equal(rows.length, 3); assert.match(rows[0].sha256, /^[a-f0-9]{64}$/);
  assert.equal(rows[0].sha256, rows[2].sha256); assert.equal(new Set(rows.map(r => r.clientFileId)).size, 3);
  assert.deepEqual(Object.keys(rows[0]).sort(), ['bytes', 'clientFileId', 'contentType', 'filename', 'sha256']);
});
test('serial raw uploads preserve slots/revisions and hand original batch to confirmation', async () => {
  const f = fixture(); await f.controller.select([file(), file('second.png', 'second', 'image/png')]); await f.controller.upload();
  assert.equal(f.controller.view.detail.import.state, 'awaiting_confirmation'); assert.deepEqual(f.reviewed, [batch]);
  assert.deepEqual(f.writes().map(c => c.method), ['POST', 'PUT', 'PUT', 'POST']);
  assert.deepEqual(f.writes('PUT').map(c => c.headers['X-Import-Revision']), ['1', '2']);
  for (const c of f.calls) { assert.equal(c.mode, 'same-origin'); assert.equal(c.credentials, 'same-origin'); assert.equal(c.cache, 'no-store'); assert.equal(c.redirect, 'error'); }
  const body = JSON.parse(f.writes()[0].body); assert.equal(body.allowTemporaryProcessing, true); assert.equal(body.consentVersion, 'media-v1');
  assert.equal('visibility' in body, false); assert.equal('accountId' in body, false);
  assert.equal(f.calls.some(c => /confirm|grants|accounts/.test(c.path)), false);
  const confirm = confirmPhotos(f.controller.view.detail.import, [slot(9)], 'original-confirm-key');
  assert.equal(confirm.confirmRequestId, 'original-confirm-key'); assert.equal(confirm.persistSelected, true);
});
test('unknown create freezes and explicit check repeats exactly the original intent', async () => {
  const f = fixture(); f.loseCreate = true; await f.controller.select([file()]); await f.controller.upload();
  assert.equal(f.controller.view.needsCheck, true); assert.equal(f.writes('PUT').length, 0);
  await f.controller.upload(); assert.equal(f.writes().length, 1);
  await f.controller.check(); assert.equal(f.writes()[0].body, f.writes()[1].body);
  assert.equal(f.writes('PUT').length, 0); await f.controller.upload(); assert.equal(f.writes('PUT').length, 1);
});
test('committed PUT with lost response is reconciled by GET, never resubmitted', async () => {
  const f = fixture(); f.losePut = true; await f.controller.select([file()]); await f.controller.upload();
  assert.equal(f.controller.view.needsCheck, true); assert.equal(f.detail.upload.files[0].status, 'successful');
  await f.controller.check(); assert.equal(f.writes('PUT').length, 1);
  await f.controller.upload(); assert.equal(f.writes('PUT').length, 1); assert.deepEqual(f.reviewed, [batch]);
});
test('committed finish with lost response is reconciled, original confirm remains a separate action', async () => {
  const f = fixture(); f.loseFinish = true; await f.controller.select([file()]); await f.controller.upload();
  const finish = f.writes().filter(c => c.path.endsWith('/finish')); assert.equal(finish.length, 1); assert.equal(f.reviewed.length, 0);
  await f.controller.check(); await f.controller.finish();
  assert.equal(f.writes().filter(c => c.path.endsWith('/finish')).length, 1); assert.equal(f.controller.view.needsCheck, false);
});
test('explicit finish409 uses fresh revision only after GET and explicit finish action', async () => {
  const f = fixture(); f.finishConflict = true; await f.controller.select([file()]); await f.controller.upload();
  const previous = JSON.parse(f.writes().at(-1).body); assert.equal(f.controller.view.needsCheck, true);
  await f.controller.check(); await f.controller.finish();
  const next = JSON.parse(f.writes().at(-1).body); assert.notEqual(next.requestId, previous.requestId); assert.ok(next.revision > previous.revision);
});
test('preflight /me404 preserves original files and can recover without a failed business write', async () => {
  const f = fixture(); await f.controller.select([file()]); f.hook = path => path === '/api/me' ? json({}, 404) : null;
  await f.controller.upload(); assert.equal(f.writes().length, 0); assert.equal(f.controller.view.unavailable, false);
  f.hook = null; await f.controller.check(); await f.controller.upload(); assert.equal(f.writes('PUT').length, 1);
});
test('post-write identity read failure holds result until explicit checking', async () => {
  const f = fixture(); await f.controller.select([file()]);
  f.afterPut = async () => { f.hook = path => path === '/api/me' ? json({}, 404) : null; };
  await f.controller.upload(); assert.equal(f.reviewed.length, 0); assert.equal(f.controller.view.needsCheck, true); assert.equal(f.controller.view.unavailable, false);
  f.hook = null; f.afterPut = null; await f.controller.check(); await f.controller.upload(); assert.equal(f.writes('PUT').length, 1);
});
test('changed identity after committed upload clears files/DTO and never exposes old result', async () => {
  const f = fixture(); await f.controller.select([file()]); f.afterPut = async () => { f.me.user.id = 'member2'; };
  await f.controller.upload(); assert.equal(f.denied, 1); assert.equal(f.controller.view.selected.length, 0); assert.equal(f.controller.view.detail, null); assert.equal(f.reviewed.length, 0);
  await f.controller.upload(); assert.equal(f.writes('PUT').length, 1);
});
test('picker return while blurred defers hashing until fresh same-identity verification', async () => {
  const f = fixture(); const photo = file(); let reads = 0; const read = photo.arrayBuffer.bind(photo); photo.arrayBuffer = () => { reads++; return read(); };
  f.current = false; f.controller.suspend(); await f.controller.select([photo]); assert.equal(reads, 0); assert.equal(f.calls.length, 0);
  f.current = true; await f.controller.resumeSelection(); assert.equal(reads, 1); assert.equal(f.calls.length, 2); assert.equal(f.writes().length, 0);
});
test('picker return after account switch does not hash or retain file selection', async () => {
  const f = fixture(); f.current = false; await f.controller.select([file()]); f.me.user.id = 'member2'; f.current = true;
  await f.controller.resumeSelection(); assert.equal(f.denied, 1); assert.equal(f.controller.view.selected.length, 0); assert.equal(f.writes().length, 0);
});
test('blur while PUT pending discards late response; later GET uses same original batch', async () => {
  const f = fixture(), g = gate(); await f.controller.select([file()]); f.afterPut = () => g.promise;
  const operation = f.controller.upload(); while (!f.writes('PUT').length) await new Promise(r => setImmediate(r));
  f.current = false; f.controller.suspend(); g.release(); await operation;
  assert.equal(f.reviewed.length, 0); assert.equal(f.controller.view.needsCheck, true);
  f.current = true; await f.controller.check(); await f.controller.upload(); assert.equal(f.writes('PUT').length, 1);
});
test('fresh page can match reselected pending SHA/bytes/type, not replace declarations', async () => {
  const f = fixture(); f.loseCreate = true; await f.controller.select([file()]); await f.controller.upload(); f.controller.dispose();
  const fresh = f.make(); await fresh.check(batch); await fresh.select([file('wrong.jpg', 'wrong')]); assert.equal(f.writes('PUT').length, 0);
  await fresh.check(); await fresh.select([file('renamed.jpg')]); await fresh.upload();
  assert.equal(f.writes('PUT').length, 1); assert.equal(f.detail.upload.files[0].filename, '合成照片.jpg');
});
test('no File after page reload does not silently skip pending; explicit finish does', async () => {
  const f = fixture(); f.loseCreate = true; await f.controller.select([file()]); await f.controller.upload(); const fresh = f.make(); await fresh.check(batch);
  await fresh.upload(); assert.equal(f.writes('PUT').length, 0); assert.equal(f.detail.import.state, 'staging');
  await fresh.finish(); assert.equal(f.detail.import.state, 'failed'); assert.equal(fresh.view.selected.length, 0); fresh.reset(); assert.equal(fresh.view.detail, null);
});
test('terminal stripped declarations are accepted while pending empty/mutated slots are rejected', async () => {
  const f = fixture(); f.loseCreate = true; await f.controller.select([file()]); await f.controller.upload(); await f.controller.check();
  const invalid = clone(f.detail); invalid.upload.files = []; assert.throws(() => readLocalImport(invalid));
  invalid.import.state = 'cancelled'; invalid.upload.canUpload = false; assert.equal(readLocalImport(invalid).upload.files.length, 0);
  f.detail.upload.files[0].slotId = slot(8); await f.controller.check(); assert.equal(f.controller.view.needsCheck, true); assert.equal(f.writes('PUT').length, 0);
});
test('busy503 does not consume slot or automatically retry', async () => {
  const f = fixture(); await f.controller.select([file()]); f.hook = (path, init) => init.method === 'PUT' ? json({ code: 'local_upload_busy' }, 503) : null;
  await f.controller.upload(); assert.equal(f.writes('PUT').length, 1); assert.equal(f.controller.view.needsCheck, true); assert.match(f.controller.view.message, /繁忙/);
  f.hook = null; await f.controller.check(); assert.equal(f.writes('PUT').length, 1); await f.controller.upload(); assert.equal(f.writes('PUT').length, 2);
});
test('true missing import becomes unavailable, unlike identity-read404', async () => {
  const f = fixture(); f.hook = path => path.includes('/media/imports/') ? json({}, 404) : null;
  await f.controller.check(batch); assert.equal(f.controller.view.unavailable, true); assert.equal(f.writes().length, 0);
});
test('oversized JSON/foreign response does not publish DTO or repeat write', async () => {
  const f = fixture(); await f.controller.select([file()]);
  f.hook = path => path === '/api/media/local-imports' ? json({ padding: 'x'.repeat(262145) }) : null;
  await f.controller.upload(); assert.equal(f.controller.view.detail, null); assert.equal(f.controller.view.needsCheck, true); assert.equal(f.writes().length, 1);
});
test('empty picker selection makes no requests; disposal forbids all late actions', async () => {
  const f = fixture(); await f.controller.select([]); assert.equal(f.calls.length, 0); f.controller.dispose(); await f.controller.select([file()]); await f.controller.upload(); assert.equal(f.calls.length, 0);
});
test('source-specific notices do not claim Google owns local photos', () => {
  assert.match(photoOriginalNotice('local-upload'), /设备上的原文件/); assert.doesNotMatch(photoOriginalNotice('local-upload'), /Google/);
  assert.match(photoOriginalNotice(), /Google Photos/); assert.equal(photoSourceLabel('local-upload'), '从设备上传');
});

test('finish intent survives preflight /me409 and later sends the identical body', async () => {
  const f = fixture(); await f.controller.select([file()]);
  f.hook = path => { if (path.endsWith('/finish')) throw new Error('synthetic uncommitted transport loss'); };
  await f.controller.upload(); const first = f.writes().find(c => c.path.endsWith('/finish')).body;
  f.hook = null; await f.controller.check();
  f.hook = path => path === '/api/me' ? json({}, 409) : null;
  await f.controller.finish(); assert.equal(f.writes().filter(c => c.path.endsWith('/finish')).length, 1);
  assert.equal(f.controller.view.needsCheck, true);
  f.hook = null; await f.controller.check(); await f.controller.finish();
  assert.equal(f.writes().filter(c => c.path.endsWith('/finish'))[1].body, first);
});
test('finish200 followed by /me409 keeps original unknown intent until actual result is checked', async () => {
  const f = fixture(); await f.controller.select([file()]);
  f.hook = path => path === '/api/me' && f.finished ? json({}, 409) : null;
  await f.controller.upload(); const writes = f.writes().filter(c => c.path.endsWith('/finish'));
  assert.equal(writes.length, 1); assert.equal(f.detail.import.state, 'awaiting_confirmation');
  assert.equal(f.controller.view.detail.import.state, 'staging'); assert.equal(f.controller.view.needsCheck, true); assert.equal(f.reviewed.length, 0);
  // Inspect only the uncertain request receipt: an acknowledged business response
  // plus failed identity read must retain the exact original key/revision.
  assert.equal(JSON.stringify(f.controller.finishIntent), writes[0].body);
  f.hook = null; await f.controller.check(); await f.controller.finish();
  assert.equal(f.writes().filter(c => c.path.endsWith('/finish')).length, 1); assert.equal(f.controller.view.detail.import.state, 'awaiting_confirmation');
});
test('local_upload_incomplete gives the same truthful skipped reason in slot and original result views', () => {
  const { photoError } = load(root + '/lib/photos.ts'), { localSlotMessage } = load(root + '/lib/localPhotoUpload.ts');
  const message = photoError('local_upload_incomplete'); assert.match(message, /尚未上传，已跳过/); assert.doesNotMatch(message, /原因未记录|Google/);
  assert.equal(localSlotMessage({ status: 'skipped', error: { code: 'local_upload_incomplete' } }), '已跳过 · ' + message);
});
