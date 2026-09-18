import { sessionIdentity } from './sessionIdentity.ts';
import type { Member } from './types';

export const MAX_DOCUMENT_FILE_BYTES = 5_000_000;
export const DOCUMENT_FILE_ACCEPT = '.pdf,.jpg,.jpeg,.png,.webp';
const formats = ['pdf', 'jpg', 'jpeg', 'png', 'webp'];
export type DocumentVisibility = 'private' | 'shared';
export type DocumentFile = Readonly<{ name: string; mimeType: string; dataBase64: string }>;
export type JourneyDocument = {
  id: string; journeyId: string | null; owner: string; title: string; filename: string;
  mimeType: 'application/pdf' | 'image/jpeg'; bytes: number; visibility: DocumentVisibility;
  segmentKey: string; unlinked: boolean; segmentMissing: boolean; createdAt: string;
  updatedAt: string; revision: number; canManage: boolean; downloadUrl: string;
};
export type DocumentList = {
  journey: { id: string; title: string; revision: number } | null;
  segments: { key: string; title: string; kind: string }[];
  journeys: { id: string; title: string }[]; documents: JourneyDocument[];
  limits: { maxFileBytes: number; formats: string[] };
};
export type DocumentUploadPayload = Readonly<{ journeyId: string; requestId: string; title: string;
  visibility: DocumentVisibility; segmentKey: string; file: DocumentFile }>;
export type DocumentPatchPayload = { revision: number; title: string; visibility: DocumentVisibility; segmentKey: string; journeyId: string | null };
export type DocumentSession = { user: Member | null; csrf?: string | null };
export type DocumentGuard = <T>(job: (csrf: string) => Promise<T>) => Promise<T>;
export class DocumentError extends Error { constructor(message: string, public status = 0) { super(message); } }
export class DocumentDiscarded extends Error {}
export class DocumentRejected extends DocumentError {}
// Only an actual endpoint response can become a definitive write rejection.
class DocumentResponseError extends DocumentError {}
function invalid(): never { throw new DocumentError('旅行资料无法安全核对，请重新读取。'); }
const object = (v: unknown): Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : invalid();
const text = (v: unknown, max: number, empty = false): string => typeof v === 'string' && Array.from(v).length <= max && (empty || !!v.trim()) && !/\p{C}/u.test(v) ? v : invalid();
// Existing journey titles may contain line breaks; React renders these as text.
const label = (v: unknown): string => typeof v === 'string' && !!v.trim() && Array.from(v).length <= 500 ? v : invalid();
const input = (v: unknown, max: number, empty = false) => text(typeof v === 'string' ? v.trim() : v, max, empty);
const integer = (v: unknown, min = 1) => typeof v === 'number' && Number.isSafeInteger(v) && v >= min ? v : invalid();
const bool = (v: unknown) => typeof v === 'boolean' ? v : invalid();
const hex = (v: unknown, size: number): string => typeof v === 'string' && new RegExp(`^[a-f0-9]{${size}}$`).test(v) ? v : invalid();
const visibility = (v: unknown): DocumentVisibility => v === 'private' || v === 'shared' ? v : invalid();
const array = (v: unknown, maximum = Infinity): unknown[] => Array.isArray(v) && v.length <= maximum ? v : invalid();
const unique = <T>(values: T[], key: (v: T) => string): T[] => new Set(values.map(key)).size === values.length ? values : invalid();
const fields = (v: Record<string, unknown>, keys: string[]) => { if (Object.keys(v).sort().join('|') !== [...keys].sort().join('|')) invalid(); };
const timestamp = (v: unknown) => { const s = text(v, 64); if (!/^\d{4}-\d\d-\d\dT.+(?:Z|\+00:00)$/.test(s) || !Number.isFinite(Date.parse(s))) invalid(); return s; };
const filename = (v: unknown) => { const s = input(v, 180); if (/[\\/]/.test(s) || s === '.' || s === '..') invalid(); return s; };
export const documentListPath = (journeyId?: string): string => '/journey-documents' + (journeyId === undefined ? '' : '?journeyId=' + hex(journeyId, 24));
export const documentPath = (id: string, file = false): string => '/journey-documents/' + hex(id, 32) + (file ? '/file' : '');

export function readDocument(raw: unknown): JourneyDocument {
  const v = object(raw), id = hex(v.id, 32), journeyId = v.journeyId === null ? null : hex(v.journeyId, 24);
  const mimeType = v.mimeType === 'application/pdf' || v.mimeType === 'image/jpeg' ? v.mimeType : invalid();
  const bytes = integer(v.bytes), unlinked = bool(v.unlinked), scope = visibility(v.visibility);
  if (unlinked !== (journeyId === null) || unlinked && scope !== 'private' || bytes > (mimeType === 'image/jpeg' ? 2_000_000 : MAX_DOCUMENT_FILE_BYTES)) invalid();
  // Ignore the server-supplied URL. It is never a navigation/download authority.
  return { id, journeyId, owner: text(v.owner, 200), title: text(v.title, 120), filename: filename(v.filename), mimeType, bytes,
    visibility: scope, segmentKey: text(v.segmentKey, 80, true), unlinked, segmentMissing: bool(v.segmentMissing),
    createdAt: timestamp(v.createdAt), updatedAt: timestamp(v.updatedAt), revision: integer(v.revision), canManage: bool(v.canManage), downloadUrl: '/api' + documentPath(id, true) };
}
export function readDocumentList(raw: unknown, journeyId?: string, ownerId?: string): DocumentList {
  const v = object(raw), j = v.journey === null ? null : object(v.journey);
  const journey = j === null ? null : { id: hex(j.id, 24), title: label(j.title), revision: integer(j.revision) };
  if ((journeyId === undefined ? null : hex(journeyId, 24)) !== (journey?.id ?? null)) invalid();
  const segments = unique(array(v.segments, 100).map(raw => { const s = object(raw); return { key: text(s.key, 80), title: label(s.title), kind: text(s.kind, 60) }; }), s => s.key);
  if (!journey && segments.length) invalid();
  const journeys = unique(array(v.journeys).map(raw => { const j = object(raw); return { id: hex(j.id, 24), title: label(j.title) }; }), j => j.id);
  const documents = unique(array(v.documents, journey ? 100 : 500).map(readDocument), d => d.id);
  for (const d of documents) {
    if (journey && d.journeyId !== journey.id || !journey && !d.canManage) invalid();
    if (ownerId !== undefined && (d.canManage !== (d.owner === ownerId) || !journey && d.owner !== ownerId || !d.canManage && d.visibility !== 'shared')) invalid();
  }
  const limits = object(v.limits), available = array(limits.formats, formats.length);
  if (limits.maxFileBytes !== MAX_DOCUMENT_FILE_BYTES || available.length !== formats.length || new Set(available).size !== formats.length || available.some(f => typeof f !== 'string' || !formats.includes(f))) invalid();
  return { journey, segments, journeys, documents, limits: { maxFileBytes: MAX_DOCUMENT_FILE_BYTES, formats: [...formats] } };
}
const fileMime = (name: string): string => {
  if (name.lastIndexOf('.') < 1) invalid();
  const extension = name.split('.').pop()!.toLowerCase();
  const mimes: Record<string, string> = { pdf: 'application/pdf', jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp' };
  return Object.hasOwn(mimes, extension) ? mimes[extension] : invalid();
};
function readFile(raw: unknown): DocumentFile {
  const f = object(raw); fields(f, ['name', 'mimeType', 'dataBase64']);
  const name = filename(f.name), mimeType = fileMime(name), data = f.dataBase64;
  if (mimeType !== f.mimeType || typeof data !== 'string' || !data || data.length > Math.ceil(MAX_DOCUMENT_FILE_BYTES / 3) * 4
    || data.length % 4 || /[^A-Za-z0-9+/=]/.test(data)) invalid();
  const padding = data.indexOf('=');
  if (padding !== -1 && (padding < data.length - 2 || !/^={1,2}$/.test(data.slice(padding)))) invalid();
  const bytes = data.length / 4 * 3 - (data.endsWith('==') ? 2 : data.endsWith('=') ? 1 : 0);
  if (bytes < 1 || bytes > MAX_DOCUMENT_FILE_BYTES) invalid();
  return Object.freeze({ name, mimeType, dataBase64: data });
}
export function readUploadPayload(raw: unknown): DocumentUploadPayload {
  const v = object(raw); fields(v, ['journeyId', 'requestId', 'title', 'visibility', 'segmentKey', 'file']);
  return Object.freeze({ journeyId: hex(v.journeyId, 24), requestId: hex(v.requestId, 32), title: input(v.title, 120),
    visibility: visibility(v.visibility), segmentKey: input(v.segmentKey, 80, true), file: readFile(v.file) });
}
export function readPatchPayload(raw: unknown): DocumentPatchPayload {
  const v = object(raw); fields(v, ['revision', 'title', 'visibility', 'segmentKey', 'journeyId']);
  const result = { revision: integer(v.revision), title: input(v.title, 120), visibility: visibility(v.visibility), segmentKey: input(v.segmentKey, 80, true), journeyId: v.journeyId === null ? null : hex(v.journeyId, 24) };
  if (result.journeyId === null && (result.visibility !== 'private' || result.segmentKey)) invalid();
  return result;
}
export function readDeletePayload(raw: unknown): { revision: number } { const v = object(raw); fields(v, ['revision']); return { revision: integer(v.revision) }; }
export function readUploadResult(raw: unknown): { document: JourneyDocument; replayed: boolean } {
  const v = object(raw), document = readDocument(v.document); if (!document.canManage) invalid();
  // A replay is the current document, including a changed or removed journey.
  return { document, replayed: bool(v.replayed) };
}
export function readMutationResult(raw: unknown, id: string): JourneyDocument {
  const d = readDocument(object(raw).document); if (d.id !== hex(id, 32) || !d.canManage) invalid(); return d;
}
export function readDeleteResult(raw: unknown, id: string): { deleted: true; id: string } {
  const v = object(raw); if (v.deleted !== true || v.id !== hex(id, 32)) invalid(); return { deleted: true, id };
}
export function newDocumentRequestId(): string {
  if (!globalThis.crypto?.getRandomValues) throw new DocumentError('当前环境无法生成安全上传编号，请使用 HTTPS 浏览器。');
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
}
export const documentSignature = sessionIdentity;
export class DocumentFence {
  private epoch = 0;
  constructor(private expected: string) {}
  invalidate() { ++this.epoch; }
  async run<T>(me: () => Promise<DocumentSession>, job: (csrf: string) => Promise<T>, current: () => boolean): Promise<T> {
    const epoch = this.epoch;
    const check = (s: DocumentSession) => {
      if (epoch !== this.epoch || !current()) throw new DocumentDiscarded();
      if (!s || typeof s !== 'object' || s.user?.role !== 'member' || typeof s.user.id !== 'string' || !s.user.id
        || typeof s.user.householdId !== 'string' || !s.user.householdId || !Number.isSafeInteger(s.user.auth_version)
        || Number(s.user.auth_version) < 1 || typeof s.csrf !== 'string' || !s.csrf || documentSignature(s) !== this.expected) throw new DocumentDiscarded('identity');
      return s.csrf;
    };
    const csrf = check(await me()); let value!: T, error: unknown, failed = false;
    try { value = await job(csrf); } catch (caught) { error = caught; failed = true; }
    check(await me()); if (failed) throw error; return value;
  }
}
export async function checkedDocumentWrite<T>(guard: DocumentGuard, write: (csrf: string) => Promise<T>): Promise<T> {
  return guard(async csrf => {
    try { return await write(csrf); } catch (e) {
      if (e instanceof DocumentResponseError && [400, 403, 404, 409, 413, 415, 422, 429].includes(e.status)) throw new DocumentRejected(e.message, e.status);
      throw e;
    }
  });
}
async function boundedBytes(response: Response, limit: number, check: () => void): Promise<Uint8Array> {
  const declared = response.headers.get('Content-Length');
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > limit)) invalid();
  if (!response.body) invalid();
  const reader = response.body.getReader(), chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) { const next = await reader.read(); check(); if (next.done) break;
      size += next.value.byteLength; if (size > limit) invalid(); chunks.push(next.value); }
  } catch (e) { await reader.cancel().catch(() => {}); throw e; } finally { reader.releaseLock(); }
  check(); if (declared !== null && Number(declared) !== size) invalid();
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; } return bytes;
}
async function fetchValue<T>(path: string, signal: AbortSignal, init: RequestInit, consume: (response: Response, check: () => void) => Promise<T>): Promise<T> {
  const controller = new AbortController(), deadline = performance.now() + 30_000, abort = () => controller.abort();
  const check = () => { if (signal.aborted) throw new DocumentDiscarded(); if (controller.signal.aborted || performance.now() >= deadline) throw new DocumentError('连接中断，请先核对旅行资料的当前状态。'); };
  check(); signal.addEventListener('abort', abort, { once: true }); const timer = setTimeout(abort, 30_000);
  try {
    const response = await fetch('/api' + path, { ...init, mode: 'same-origin', credentials: 'same-origin', redirect: 'error', cache: 'no-store', signal: controller.signal });
    check(); if (response.redirected) invalid();
    if (!response.ok) throw new DocumentResponseError(response.status === 409 ? '资料或关联已变化，请读取最新状态后核对。' : [401, 403].includes(response.status)
      ? '当前身份或权限需要重新核对。' : response.status === 404 ? '资料或旅行不存在，或当前不可见。' : '暂时无法读取或保存旅行资料。', response.status);
    const result = await consume(response, check); check(); return result;
  } catch (e) { check(); if (e instanceof DocumentError || e instanceof DocumentDiscarded) throw e; throw new DocumentError('连接中断，请先核对旅行资料的当前状态。'); }
  finally { clearTimeout(timer); signal.removeEventListener('abort', abort); }
}
export async function documentRequest(path: string, signal: AbortSignal, options: { method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'; payload?: unknown; csrf?: string } = {}): Promise<unknown> {
  const method = options.method ?? 'GET'; let payload: unknown;
  if (method === 'GET') { if (path !== '/me' && !/^\/journey-documents(?:\?journeyId=[a-f0-9]{24})?$/.test(path) || options.payload !== undefined) invalid(); }
  else {
    if (!options.csrf) invalid();
    if (method === 'POST' && path === '/journey-documents') payload = readUploadPayload(options.payload);
    else if (/^\/journey-documents\/[a-f0-9]{32}$/.test(path) && method === 'PATCH') payload = readPatchPayload(options.payload);
    else if (/^\/journey-documents\/[a-f0-9]{32}$/.test(path) && method === 'DELETE') payload = readDeletePayload(options.payload);
    else invalid();
  }
  return fetchValue(path, signal, { method, headers: { 'Content-Type': 'application/json', ...(method === 'GET' ? {} : { 'X-CSRF-Token': options.csrf! }) }, ...(payload === undefined ? {} : { body: JSON.stringify(payload) }) }, async (response, check) => {
    if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') invalid();
    const bytes = await boundedBytes(response, 4_000_000, check); return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  });
}
export async function readDocumentFile(file: File, signal: AbortSignal, current: () => boolean = () => true): Promise<DocumentFile> {
  const check = () => { if (signal.aborted || !current()) throw new DocumentDiscarded(); };
  check();
  if (!file || typeof file.arrayBuffer !== 'function' || typeof btoa !== 'function') throw new DocumentError('当前原生环境尚未接入文件选择，请使用网页浏览器。');
  const name = filename(file.name), mimeType = fileMime(name);
  if (!Number.isSafeInteger(file.size) || file.size < 1 || file.size > MAX_DOCUMENT_FILE_BYTES || file.type && file.type !== mimeType) throw new DocumentError('请使用不超过 5 MB、扩展名与类型一致的 PDF、JPG、PNG 或 WebP。');
  const bytes = new Uint8Array(await file.arrayBuffer()); check(); if (bytes.length !== file.size) invalid();
  let binary = ''; for (let i = 0; i < bytes.length; i += 8192) { check(); binary += String.fromCharCode(...bytes.subarray(i, i + 8192)); }
  check(); return readFile({ name, mimeType, dataBase64: btoa(binary) });
}
export async function downloadDocument(raw: JourneyDocument, signal: AbortSignal, guard: DocumentGuard, current: () => boolean): Promise<{ blob: Blob; filename: string }> {
  const doc = readDocument(raw);
  const result = await guard(() => fetchValue(documentPath(doc.id, true), signal, { method: 'GET' }, async (response, check) => {
    const live = () => { check(); if (!current()) throw new DocumentDiscarded(); }; live();
    if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== doc.mimeType
      || !/^attachment(?:;|$)/i.test(response.headers.get('Content-Disposition') || '')
      || !/(?:^|,)\s*no-store\s*(?:,|$)/i.test(response.headers.get('Cache-Control') || '')
      || response.headers.get('X-Content-Type-Options')?.toLowerCase() !== 'nosniff') invalid();
    const bytes = await boundedBytes(response, doc.bytes, live); if (bytes.length !== doc.bytes) invalid(); live();
    return { blob: new Blob([bytes as Uint8Array<ArrayBuffer>], { type: doc.mimeType }), filename: doc.filename };
  }));
  if (signal.aborted || !current()) throw new DocumentDiscarded(); return result;
}
