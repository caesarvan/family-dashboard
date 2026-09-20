import { ApiError } from './api.ts';
import { CONSENT, PhotoReadDiscarded, PhotoReadFence, isMediaId, newPhotoRequestId, photoError, terminalImport, validateImport } from './photos.ts';
import type { ImportDetail, PhotoSession, PhotoUploadFile } from './photos.ts';

export const LOCAL_PHOTO_LIMIT = 8 * 1024 * 1024;
export const LOCAL_PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
type Declaration = Pick<PhotoUploadFile, 'clientFileId' | 'filename' | 'contentType' | 'bytes' | 'sha256'>;
type CreateIntent = { requestId: string; consentVersion: string; allowTemporaryProcessing: true; files: Declaration[] };
export type LocalUploadView = {
  busy: boolean; selected: Declaration[]; detail: ImportDetail | null; needsCheck: boolean;
  message: string; unavailable: boolean; uploading: string;
};
class LocalImportUnavailable extends ApiError {}
const key = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{16,100}$/.test(value);
const filename = (value: unknown): value is string => typeof value === 'string' && !!value.trim()
  && new TextEncoder().encode(value).length <= 255 && !/[\x00-\x1f\x7f/\\]/.test(value) && !['.', '..'].includes(value);
function declaration(value: Declaration) {
  return key(value.clientFileId) && filename(value.filename) && LOCAL_PHOTO_TYPES.includes(value.contentType)
    && Number.isSafeInteger(value.bytes) && value.bytes > 0 && value.bytes <= LOCAL_PHOTO_LIMIT && /^[a-f0-9]{64}$/.test(value.sha256);
}
export function localUploadError(error: unknown): string {
  if (error instanceof PhotoReadDiscarded) return '页面或身份已变化，请回到相册核对本次上传。';
  if (error instanceof ApiError) {
    if (error.code === 'local_upload_busy' || error.status === 503) return '照片处理暂时繁忙。请先核对状态，再继续本次上传。';
    if (error.code === 'local_upload_mismatch' || error.status === 422) return '文件与本次声明不一致，请重新选择同一张原文件后核对。';
    if (error instanceof LocalImportUnavailable) return '本次上传已移除、过期或不再可见。不会重新创建。';
    if (error.status === 409) return '本次上传已有变化。请核对当前状态，再决定是否继续。';
    if (error.status === 413) return '文件超过 8 MiB，不能上传。';
    if (error.status === 429) return '上传次数暂时受限，请稍后核对本次状态。';
    return '上传结果尚未确认。请先核对状态，不会自动重复上传。';
  }
  return error instanceof Error ? error.message : '暂时无法处理照片，请核对后重试。';
}
export function readLocalImport(raw: ImportDetail, expectedId?: string): ImportDetail {
  const value = validateImport(raw), upload = value.upload;
  if (value.import.source !== 'local-upload' || expectedId && value.import.id !== expectedId
    || !upload || typeof upload.canUpload !== 'boolean' || !Array.isArray(upload.files)
    || (upload.files.length < 1 && !terminalImport(value.import.state)) || upload.files.length > 10) throw new Error('本次设备上传记录无法核对。');
  const ids = new Set(), slots = new Set();
  for (const file of upload.files) {
    if (!declaration(file) || !isMediaId(file.slotId) || ids.has(file.clientFileId) || slots.has(file.slotId)
      || !['pending', 'successful', 'duplicate', 'failed', 'skipped'].includes(file.status)) throw new Error('上传文件清单无法核对。');
    ids.add(file.clientFileId); slots.add(file.slotId);
  }
  if (upload.canUpload && (terminalImport(value.import.state) || value.import.state === 'awaiting_confirmation')) throw new Error('上传状态无法核对。');
  return value;
}
export async function describeLocalFiles(files: File[], valid: () => boolean): Promise<Declaration[]> {
  if (!files.length || files.length > 10) throw new Error('一次请选择 1～10 张照片。');
  // Validate the entire selection before reading any bytes. Hash one bounded file
  // at a time; never retain array buffers/base64 or infer dates from lastModified.
  for (const file of files) {
    if (!(file instanceof Blob) || !filename(file.name)) throw new Error('文件名无法使用，请选择名称完整的照片。');
    if (!LOCAL_PHOTO_TYPES.includes(file.type)) throw new Error('仅支持 JPEG、PNG、WebP 照片；暂不支持 HEIC、视频或动图。');
    if (!file.size || file.size > LOCAL_PHOTO_LIMIT) throw new Error('每张照片须为 1 字节至 8 MiB。');
  }
  const result: Declaration[] = [];
  for (const file of files) {
    if (!valid()) throw new PhotoReadDiscarded();
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    if (!valid()) throw new PhotoReadDiscarded();
    result.push({ clientFileId: newPhotoRequestId(), filename: file.name, contentType: file.type, bytes: file.size,
      sha256: Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('') });
  }
  return result;
}

// A page-owned controller survives file-picker blur and temporary UI concealment.
// Its files/intents live only in memory; disposing or changing identity clears them.
export class LocalPhotoUpload {
  view: LocalUploadView = { busy: false, selected: [], detail: null, needsCheck: false, message: '', unavailable: false, uploading: '' };
  private listeners = new Set<() => void>();
  private requests = new Set<AbortController>();
  private files = new Map<string, File>();
  private pendingSelection: File[] | null = null;
  private intent: CreateIntent | null = null;
  private finishIntent: { revision: number; requestId: string } | null = null;
  private generation = 0;
  private alive = true;
  private running = false;
  private session: PhotoSession | null = null;
  private fence: PhotoReadFence;
  constructor(private options: { user: NonNullable<PhotoSession['user']>; identityKey?: string;
    current: () => boolean; denied: () => void; review: (id: string) => Promise<void>; transport?: typeof fetch }) {
    this.fence = new PhotoReadFence(async () => { const me = await this.request<PhotoSession>('/me'); this.session = me; return me; }, options.user, options.identityKey);
  }
  subscribe(callback: () => void) { this.listeners.add(callback); return () => { this.listeners.delete(callback); }; }
  private set(patch: Partial<LocalUploadView>) { this.view = { ...this.view, ...patch }; this.listeners.forEach(fn => fn()); }
  private current = () => this.alive && !this.view.unavailable && this.options.current();
  private async request<T>(path: string, method = 'GET', body?: object | File, revision?: number): Promise<T> {
    if (!(method === 'GET' && (path === '/me' || /^\/media\/imports\/[a-f0-9]{24}$/.test(path))
      || method === 'POST' && (path === '/media/local-imports' || /^\/media\/local-imports\/[a-f0-9]{24}\/finish$/.test(path))
      || method === 'PUT' && /^\/media\/local-imports\/[a-f0-9]{24}\/files\/[a-f0-9]{24}$/.test(path))) throw new Error('上传路径无法核对。');
    const controller = new AbortController(); this.requests.add(controller);
    const timeout = setTimeout(() => controller.abort(), 60000);
    try {
      if (method !== 'GET' && !this.session?.csrf) throw new Error('请先核对登录身份。');
      const response = await (this.options.transport || fetch)('/api' + path, { method, mode: 'same-origin', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
        headers: { Accept: 'application/json', 'Content-Type': method === 'PUT' ? (body as File).type : 'application/json',
          ...(method !== 'GET' ? { 'X-CSRF-Token': this.session!.csrf! } : {}), ...(revision !== undefined ? { 'X-Import-Revision': String(revision) } : {}) },
        ...(body ? { body: method === 'PUT' ? body as File : JSON.stringify(body) } : {}) });
      if (response.redirected || !response.body || response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') throw new ApiError('上传响应无法核对。', response.ok ? 0 : response.status);
      const reader = response.body.getReader(); let bytes = 0, text = ''; const decoder = new TextDecoder('utf-8', { fatal: true });
      try { for (;;) { const part = await reader.read(); if (part.done) break; bytes += part.value.byteLength;
        if (bytes > 262144) throw new ApiError('上传响应过大。'); text += decoder.decode(part.value, { stream: true }); }
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
      let value: any; try { value = JSON.parse(text + decoder.decode()); } catch { throw new ApiError('上传响应无法核对。', response.ok ? 0 : response.status); }
      if (!response.ok) {
        const Failure = path !== '/me' && [404, 410].includes(response.status) ? LocalImportUnavailable : ApiError;
        throw new Failure('设备上传暂时未完成。', response.status, typeof value?.code === 'string' ? value.code : '');
      }
      return value as T;
    } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError('上传连接中断，请核对状态。'); }
    finally { clearTimeout(timeout); this.requests.delete(controller); }
  }
  private guarded<T>(action: () => Promise<T>) {
    const generation = this.generation;
    return this.fence.read(action, () => this.current() && generation === this.generation);
  }
  private accept(value: ImportDetail) {
    const data = readLocalImport(value, this.view.detail?.import.id);
    const expected = this.intent?.files || this.view.selected;
    const terminal = terminalImport(data.import.state);
    if (!terminal && expected.length && (expected.length !== data.upload!.files.length || expected.some((f, i) => {
      const row = data.upload!.files[i]; return Object.keys(f).some(k => f[k as keyof Declaration] !== row[k as keyof Declaration]);
    }))) throw new Error('上传声明已变化，请保留原批次并核对。');
    const oldSlots = this.view.detail?.upload?.files;
    if (!terminal && oldSlots && oldSlots.some((f, i) => f.slotId !== data.upload!.files[i]?.slotId)) throw new Error('上传文件标识已变化。');
    this.set({ detail: data, selected: data.upload!.files.map(({ clientFileId, filename, contentType, bytes, sha256 }) => ({ clientFileId, filename, contentType, bytes, sha256 })), needsCheck: false });
    if (!data.upload!.canUpload) { this.files.clear(); this.finishIntent = null; }
    return data;
  }
  private async action(work: () => Promise<void>) {
    if (this.running || !this.current()) return;
    this.running = true; this.set({ busy: true, message: '' });
    try { await work(); }
    catch (error) {
      if (!this.alive) return;
      if (error instanceof PhotoReadDiscarded && error.message === 'identity' || error instanceof ApiError && [401, 403].includes(error.status)) {
        this.clear(); this.set({ unavailable: true, message: '身份或权限已变化，已清空本次页面内的文件。' }); this.options.denied(); return;
      }
      this.set({ needsCheck: !!this.intent || !!this.view.detail, message: localUploadError(error),
        ...(error instanceof LocalImportUnavailable ? { unavailable: true } : {}) });
    } finally { this.running = false; if (this.alive) this.set({ busy: false, uploading: '' }); }
  }
  async select(files: File[]) {
    if (!files.length) return; // Picker cancel is neither a write nor a success.
    if (!this.alive || this.view.unavailable || this.running) return;
    if (!this.current()) { this.pendingSelection = files; return; }
    this.pendingSelection = null;
    await this.action(async () => {
      if (this.intent && !this.view.detail) throw new Error('请先核对原批次的创建结果。');
      const generation = this.generation;
      const values = await this.guarded(() => describeLocalFiles(files, () => this.current() && generation === this.generation));
      if (this.view.detail) {
        if (this.view.needsCheck || !this.view.detail.upload?.canUpload) throw new Error('请先核对本次上传状态。');
        const pending = [...this.view.detail.upload.files.filter(f => f.status === 'pending')];
        const matches = values.map((f, index) => { const i = pending.findIndex(p => p.sha256 === f.sha256 && p.bytes === f.bytes && p.contentType === f.contentType);
          if (i < 0) throw new Error('重选文件必须与本批尚未上传的原文件完全一致。'); return { id: pending.splice(i, 1)[0].clientFileId, file: files[index] }; });
        matches.forEach(m => this.files.set(m.id, m.file)); this.set({ message: '已重新核对原文件，可以继续本批上传。' });
      } else {
        this.files.clear(); values.forEach((v, i) => this.files.set(v.clientFileId, files[i])); this.set({ selected: values, needsCheck: false, message: '' });
      }
    });
  }
  async resumeSelection() {
    if (this.pendingSelection && this.current() && !this.running) await this.select(this.pendingSelection);
  }
  async upload() {
    await this.action(async () => {
      if (this.view.needsCheck) throw new Error('请先核对本次上传状态。');
      if (!this.view.detail) {
        if (!this.view.selected.length) throw new Error('请先选择照片。');
        this.intent ||= { requestId: newPhotoRequestId(), consentVersion: CONSENT, allowTemporaryProcessing: true, files: this.view.selected.map(f => ({ ...f })) };
        this.accept(await this.guarded(() => this.request<ImportDetail>('/media/local-imports', 'POST', this.intent!)));
      }
      for (;;) {
        const data = this.view.detail!; if (!data.upload!.canUpload) break;
        const slot = data.upload!.files.find(f => f.status === 'pending'); if (!slot) { await this.finishWork(); return; }
        const file = this.files.get(slot.clientFileId);
        if (!file) { this.set({ message: '还有照片未上传。请重新选择原文件，或结束本批并核对已成功的照片。' }); return; }
        this.set({ uploading: slot.filename });
        const result = await this.guarded(() => this.request<ImportDetail>('/media/local-imports/' + data.import.id + '/files/' + slot.slotId, 'PUT', file, data.import.revision));
        const next = this.accept(result);
        if (next.upload!.files.find(f => f.slotId === slot.slotId)?.status === 'pending') throw new Error('这张照片的结果尚未确认，请核对状态。');
        this.files.delete(slot.clientFileId);
      }
      if (this.view.detail?.import.canConfirm) await this.options.review(this.view.detail.import.id);
    });
  }
  private async finishWork() {
    const data = this.view.detail; if (!data) throw new Error('请先核对本次上传。');
    if (data.upload?.canUpload) {
      this.finishIntent ||= { revision: data.import.revision, requestId: newPhotoRequestId() };
      try { this.accept(await this.guarded(() => this.request<ImportDetail>('/media/local-imports/' + data.import.id + '/finish', 'POST', this.finishIntent!))); }
      catch (error) {
        // An explicit revision rejection did not accept this intent. Other errors
        // retain it until the original record is checked, including lost responses.
        if (error instanceof ApiError && error.status === 409) this.finishIntent = null;
        throw error;
      }
    }
    if (this.view.detail) await this.options.review(this.view.detail.import.id);
  }
  async finish() { await this.action(async () => { if (this.view.needsCheck) throw new Error('请先核对原批次。'); await this.finishWork(); }); }
  async check(id?: string) {
    await this.action(async () => {
      if (id && this.view.detail && id !== this.view.detail.import.id && !terminalImport(this.view.detail.import.state)) throw new Error('请先结束当前批次。');
      if (id && this.view.detail && id !== this.view.detail.import.id) this.clear();
      const target = id || this.view.detail?.import.id;
      if (target && !isMediaId(target)) throw new Error('上传记录无法核对。');
      const value = target ? await this.guarded(() => this.request<ImportDetail>('/media/imports/' + target))
        : this.intent ? await this.guarded(() => this.request<ImportDetail>('/media/local-imports', 'POST', this.intent!)) : null;
      if (!value) { await this.guarded(async () => true); this.set({ needsCheck: false }); return; }
      const data = this.accept(value);
      this.set({ message: data.upload!.canUpload ? '已核对当前状态。只有你点击继续，才会上传剩余文件。' : '已读取本批结果，请核对预览后保存。' });
      if (!data.upload!.canUpload) await this.options.review(data.import.id);
    });
  }
  observe(value: ImportDetail) {
    // Parent already applied its own /me fence. Never replace a different batch.
    if (this.running || value.import.source !== 'local-upload' || value.import.id !== this.view.detail?.import.id || value.import.revision < this.view.detail.import.revision) return;
    try { this.accept(value); } catch { this.set({ needsCheck: true }); }
  }
  suspend() { ++this.generation; this.fence.invalidate(); this.requests.forEach(r => r.abort());
    if (this.intent || this.view.detail) this.set({ needsCheck: true, message: '上传已暂停；请求可能已完成，回到页面后请先核对。' }); }
  private clear() { this.pendingSelection = null; this.files.clear(); this.intent = null; this.finishIntent = null; this.set({ selected: [], detail: null, needsCheck: false }); }
  reset() { if (!this.running && (!this.intent && !this.view.detail || this.view.detail && terminalImport(this.view.detail.import.state))) { this.clear(); this.set({ message: '', unavailable: false }); } }
  dispose() { this.alive = false; this.listeners.clear(); this.suspend(); this.clear(); }
}

export function pickLocalPhotos(): Promise<File[]> {
  if (typeof document === 'undefined') return Promise.reject(new Error('请在手机或电脑浏览器中选择照片。'));
  return new Promise((resolve, reject) => {
    const input = document.createElement('input'); input.type = 'file'; input.multiple = true;
    input.accept = LOCAL_PHOTO_TYPES.join(','); input.setAttribute('aria-label', '选择设备照片'); input.style.display = 'none';
    const done = (files: File[]) => { input.remove(); resolve(files); };
    input.addEventListener('change', () => done(Array.from(input.files || [])), { once: true });
    input.addEventListener('cancel', () => done([]), { once: true }); document.body.appendChild(input);
    try { input.click(); } catch { input.remove(); reject(new Error('无法打开文件选择器，请使用浏览器选择照片。')); }
  });
}

export const localSlotMessage = (file: PhotoUploadFile) => ({ pending: '待上传', successful: '预览已就绪', duplicate: '已保存过，可复用', failed: '未成功', skipped: '已跳过' }[file.status])
  + (file.error?.code ? ' · ' + photoError(file.error.code) : '');
