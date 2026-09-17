import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DocumentError, DocumentDiscarded, DocumentRejected, DocumentFence, documentSignature, documentRequest,
  checkedDocumentWrite, readDocument, readDocumentList, readUploadPayload, readPatchPayload, readDeletePayload,
  readUploadResult, readMutationResult, readDeleteResult, documentListPath, documentPath, newDocumentRequestId,
  readDocumentFile, downloadDocument, MAX_DOCUMENT_FILE_BYTES } from '../frontend/src/lib/journeyDocuments.ts';

const journeyId = 'a'.repeat(24), id = 'd'.repeat(32), requestId = 'b'.repeat(32);
const pdf = Buffer.from('%PDF-1.7\n%%EOF\n');
const file = () => ({ name: 'synthetic.pdf', mimeType: 'application/pdf', dataBase64: pdf.toString('base64') });
const doc = (patch = {}) => ({ id, journeyId, owner: 'member1', title: '合成行程凭证', filename: 'synthetic.pdf', mimeType: 'application/pdf', bytes: pdf.length,
  visibility: 'private', segmentKey: '', unlinked: false, segmentMissing: false, createdAt: '2026-09-17T00:00:00.000000+00:00', updatedAt: '2026-09-17T00:00:00Z', revision: 1,
  canManage: true, downloadUrl: '/api' + documentPath(id, true), ...patch });
const list = (patch = {}) => ({ journey: { id: journeyId, title: '合成旅行', revision: 1 }, segments: [], journeys: [{ id: journeyId, title: '合成旅行' }], documents: [doc()], limits: { maxFileBytes: 5000000, formats: ['pdf', 'jpg', 'jpeg', 'png', 'webp'] }, ...patch });
const upload = (patch = {}) => ({ journeyId, requestId, title: '合成凭证', visibility: 'private', segmentKey: '', file: file(), ...patch });
const patch = (change = {}) => ({ revision: 1, title: '改名', visibility: 'private', segmentKey: '', journeyId, ...change });
const session = () => ({ user: { id: 'member1', name: 'Synthetic', role: 'member', householdId: 'default', auth_version: 1 }, csrf: 'synthetic-csrf' });
const guard = (s = session(), current = () => true) => { const fence = new DocumentFence(documentSignature(s)); return job => fence.run(async () => s, job, current); };
const signal = () => new AbortController().signal;
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const attachment = (body = pdf, headers = {}) => new Response(body, { headers: { 'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="synthetic.pdf"', 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', ...headers } });
async function withFetch(mock, action) { const original = globalThis.fetch; globalThis.fetch = mock; try { return await action(); } finally { globalThis.fetch = original; } }

test('document ID, safe download route and orphan projections follow the actual API', () => {
  assert.equal(readDocument(doc({ downloadUrl: 'https://evil.example/private' })).downloadUrl, '/api/journey-documents/' + id + '/file');
  const orphan = readDocument(doc({ journeyId: null, unlinked: true, segmentKey: 'removed', segmentMissing: true }));
  assert.equal(orphan.segmentKey, 'removed'); assert.equal(orphan.visibility, 'private');
  for (const value of [doc({ id: journeyId }), doc({ journeyId: id }), doc({ unlinked: true }), doc({ journeyId: null, unlinked: true, visibility: 'shared' }), doc({ bytes: true }), doc({ mimeType: 'image/png' }), doc({ filename: '../secret.pdf' })]) assert.throws(() => readDocument(value), DocumentError);
  assert.equal(documentListPath(), '/journey-documents'); assert.equal(documentListPath(journeyId), '/journey-documents?journeyId=' + journeyId);
  for (const bad of ['../file', id + '?x=1', 'https://evil.test']) assert.throws(() => documentPath(bad), DocumentError);
});

test('list scope cannot quietly switch journey, show another owner in the personal library or inflate limits', () => {
  assert.equal(readDocumentList(list(), journeyId, 'member1').documents.length, 1);
  const shared = doc({ owner: 'member2', canManage: false, visibility: 'shared' });
  assert.equal(readDocumentList(list({ documents: [shared] }), journeyId, 'member1').documents[0].canManage, false);
  assert.throws(() => readDocumentList(list(), 'f'.repeat(24), 'member1'), DocumentError);
  assert.throws(() => readDocumentList(list({ journey: null, documents: [shared] }), undefined, 'member1'), DocumentError);
  assert.throws(() => readDocumentList(list({ documents: [doc(), doc()] }), journeyId, 'member1'), DocumentError);
  assert.throws(() => readDocumentList(list({ limits: { maxFileBytes: 9999999, formats: ['pdf'] } }), journeyId), DocumentError);
  const many = Array.from({ length: 500 }, (_, i) => doc({ id: i.toString(16).padStart(32, '0') }));
  assert.equal(readDocumentList(list({ journey: null, documents: many }), undefined, 'member1').documents.length, 500);
});

test('frozen upload retains its original bytes and request ID despite later form edits', () => {
  const draft = upload(), frozen = readUploadPayload(draft); draft.title = 'different'; draft.file.dataBase64 = 'AAAA';
  assert.equal(frozen.title, '合成凭证'); assert.equal(frozen.file.dataBase64, pdf.toString('base64')); assert.equal(frozen.requestId, requestId);
  assert(Object.isFrozen(frozen)); assert(Object.isFrozen(frozen.file));
  for (const value of [upload({ requestId: journeyId }), upload({ owner: 'member2' }), upload({ file: { ...file(), dataBase64: 'data:application/pdf;base64,AAAA' } }), upload({ file: { ...file(), dataBase64: 'AA=A' } }), upload({ file: { ...file(), name: '.pdf' } }), upload({ file: { ...file(), name: 'pdf' } }), upload({ file: { ...file(), mimeType: 'text/html' } })]) assert.throws(() => readUploadPayload(value), DocumentError);
  assert.equal(readUploadPayload(upload({ title: '😀'.repeat(120) })).title.length, 240);
  assert.throws(() => readUploadPayload(upload({ title: '😀'.repeat(121) })), DocumentError);
  assert.match(newDocumentRequestId(), /^[a-f0-9]{32}$/);
});

test('metadata updates require all five fields and explicit private unlink; delete has only a version', () => {
  assert.equal(readPatchPayload(patch({ journeyId: null })).journeyId, null);
  for (const value of [{ title: 'title', revision: 1 }, patch({ owner: 'other' }), patch({ revision: true }), patch({ journeyId: null, visibility: 'shared' }), patch({ journeyId: null, segmentKey: 'hotel' })]) assert.throws(() => readPatchPayload(value), DocumentError);
  assert.deepEqual(readDeletePayload({ revision: 2 }), { revision: 2 });
  assert.throws(() => readDeletePayload({ revision: 2, requestId }), DocumentError);
});

test('upload replay is current metadata, not an immutable receipt or a forced return to the old journey', () => {
  const current = doc({ title: '后来改名', journeyId: null, unlinked: true, revision: 8 });
  const result = readUploadResult({ document: current, replayed: true });
  assert.equal(result.document.journeyId, null); assert.equal(result.document.revision, 8);
  assert.throws(() => readUploadResult({ document: current }), DocumentError);
  assert.throws(() => readMutationResult({ document: current }, 'e'.repeat(32)), DocumentError);
  assert.deepEqual(readDeleteResult({ deleted: true, id }, id), { deleted: true, id });
  assert.throws(() => readDeleteResult({ deleted: false, id }, id), DocumentError);
});

test('identity fence checks every member dimension before dispatch and after response', async () => {
  const original = session();
  for (const changed of [{ ...original, csrf: 'new' }, { ...original, user: { ...original.user, id: 'member2' } }, { ...original, user: { ...original.user, householdId: 'other' } }, { ...original, user: { ...original.user, auth_version: 2 } }, { ...original, user: { ...original.user, role: 'tv' } }]) {
    const fence = new DocumentFence(documentSignature(original)); let calls = 0;
    await assert.rejects(fence.run(async () => ++calls === 1 ? original : changed, async () => 'private bytes', () => true), DocumentDiscarded);
  }
  const missing = { ...original, user: { ...original.user, auth_version: undefined } }; let dispatched = false;
  await assert.rejects(new DocumentFence(documentSignature(missing)).run(async () => missing, async () => { dispatched = true; }, () => true), DocumentDiscarded);
  assert.equal(dispatched, false);
});

test('background, offline or invalidated work never publishes a late successful result', async () => {
  const s = session();
  for (const invalidate of [false, true]) {
    const fence = new DocumentFence(documentSignature(s)); let current = true;
    await assert.rejects(fence.run(async () => s, async () => { if (invalidate) fence.invalidate(); else current = false; return 'late'; }, () => current), DocumentDiscarded);
  }
});

test('only a real write refusal with valid post-check is definitive; auth/network/after-check failures remain unknown', async () => {
  const send = () => documentRequest('/journey-documents', signal(), { method: 'POST', payload: upload(), csrf: session().csrf });
  for (const status of [400, 403, 404, 409, 413, 415, 422, 429]) await withFetch(async () => json({ error: 'refused' }, status), async () => assert.rejects(checkedDocumentWrite(guard(), send), DocumentRejected));
  for (const status of [401, 408, 500, 503]) await withFetch(async () => json({ error: 'uncertain' }, status), async () => assert.rejects(checkedDocumentWrite(guard(), send), e => e instanceof DocumentError && !(e instanceof DocumentRejected)));
  await withFetch(async () => json({ error: 'refused' }, 409), async () => {
    let reads = 0; const fence = new DocumentFence(documentSignature(session()));
    await assert.rejects(checkedDocumentWrite(job => fence.run(async () => { if (++reads === 2) throw new DocumentError('cannot verify'); return session(); }, job, () => true), send), e => e.message === 'cannot verify' && !(e instanceof DocumentRejected));
  });
  await assert.rejects(checkedDocumentWrite(guard(), async () => { throw new DocumentError('not a response', 409); }), e => !(e instanceof DocumentRejected));
});

test('transport enforces local route, bounded JSON and no retry after a sent upload loses its response', async () => {
  let writes = 0;
  await withFetch(async (url, options) => {
    assert.equal(url, '/api/journey-documents'); assert.equal(options.mode, 'same-origin'); assert.equal(options.credentials, 'same-origin'); assert.equal(options.redirect, 'error'); assert.equal(options.cache, 'no-store');
    ++writes; assert.equal(JSON.parse(options.body).requestId, requestId); throw new TypeError('response lost');
  }, async () => assert.rejects(checkedDocumentWrite(guard(), csrf => documentRequest('/journey-documents', signal(), { method: 'POST', payload: readUploadPayload(upload()), csrf })), DocumentError));
  assert.equal(writes, 1);
  await withFetch(async () => { throw Error('must not fetch'); }, async () => {
    for (const path of ['https://evil.test', '//evil.test', '/journey-documents?owner=other', documentPath(id, true)]) await assert.rejects(documentRequest(path, signal()), DocumentError);
  });
  await withFetch(async () => new Response('not JSON', { headers: { 'Content-Type': 'text/html' } }), async () => assert.rejects(documentRequest('/me', signal()), DocumentError));
});

test('real File bytes round-trip at 5MB and reject wrong MIME, overflow and stale selection', async () => {
  const bytes = Buffer.alloc(MAX_DOCUMENT_FILE_BYTES, 42), max = new File([bytes], 'max.pdf', { type: 'application/pdf' });
  const result = await readDocumentFile(max, signal()); assert.equal(Buffer.from(result.dataBase64, 'base64').length, MAX_DOCUMENT_FILE_BYTES);
  await assert.rejects(readDocumentFile(new File([Buffer.alloc(MAX_DOCUMENT_FILE_BYTES + 1)], 'large.pdf'), signal()), DocumentError);
  await assert.rejects(readDocumentFile(new File([pdf], 'wrong.png', { type: 'application/pdf' }), signal()), DocumentError);
  const pending = { name: 'synthetic.pdf', type: '', size: pdf.length, arrayBuffer: async () => { alive = false; return pdf.buffer.slice(pdf.byteOffset, pdf.byteOffset + pdf.length); } }; let alive = true;
  await assert.rejects(readDocumentFile(pending, signal(), () => alive), DocumentDiscarded);
  const emptyType = await readDocumentFile(new File([pdf], 'synthetic.PDF'), signal()); assert.equal(emptyType.mimeType, 'application/pdf');
});

test('download uses ID rather than supplied URL and releases bytes only after full identity verification', async () => {
  await withFetch(async (url, options) => { assert.equal(url, '/api/journey-documents/' + id + '/file'); assert.equal(options.redirect, 'error'); return attachment(); }, async () => {
    const result = await downloadDocument(doc({ downloadUrl: 'data:text/html,not-used' }), signal(), guard(), () => true);
    assert.deepEqual(Buffer.from(await result.blob.arrayBuffer()), pdf); assert.equal(result.filename, 'synthetic.pdf');
  });
  await withFetch(async () => attachment(), async () => {
    const original = session(); let reads = 0; const fence = new DocumentFence(documentSignature(original));
    await assert.rejects(downloadDocument(doc(), signal(), job => fence.run(async () => ++reads === 1 ? original : { ...original, csrf: 'new' }, job, () => true), () => true), DocumentDiscarded);
  });
});

test('download rejects HTML, inline/cacheable content, oversized streams and aborted late bytes', async () => {
  for (const headers of [{ 'Content-Type': 'text/html' }, { 'Content-Disposition': 'inline' }, { 'Cache-Control': 'public,max-age=60' }, { 'X-Content-Type-Options': '' }]) await withFetch(async () => attachment(pdf, headers), async () => assert.rejects(downloadDocument(doc(), signal(), guard(), () => true), DocumentError));
  await withFetch(async () => attachment(Buffer.concat([pdf, pdf])), async () => assert.rejects(downloadDocument(doc(), signal(), guard(), () => true), DocumentError));
  const controller = new AbortController();
  await withFetch(async () => { controller.abort(); return attachment(); }, async () => assert.rejects(downloadDocument(doc(), controller.signal, guard(), () => true), DocumentDiscarded));
});
