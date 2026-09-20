import { sessionIdentity } from './sessionIdentity.ts';
// Local media contracts. Provider URLs never become preview image sources.
export type Photo = {
  id: string; revision: number; caption: string; width: number; height: number;
  previewUrl: string; visibility: 'private' | 'shared'; canManage: boolean; createdAt: string;
  journey: { id: string; tripId: string; title: string } | null;
  accountId?: string | null; displayFilename?: string; source?: 'google-photos' | 'local-upload';
  sourceCreatedAt?: string | null; sourceTimeState?: 'known' | 'unknown';
  mediaType?: 'photo' | 'video'; durationMs?: number; hasAudio?: boolean; videoUrl?: string;
};
export type PhotoImport = {
  source?: 'google-photos' | 'local-upload';
  id: string; revision: number; state: string; createdAt: string; expiresAt: string;
  nextPollAt: string | null; canConfirm: boolean; pickerUri?: string;
  resultsState: 'known' | 'unknown';
  counts: Record<'selected' | 'ready' | 'failed' | 'skipped' | 'pending' | 'saved' | 'unselected', number | null>;
  results: { position: number; status: string; error?: { code: string } }[];
  error?: { code: string }; cleanupPending: boolean;
};
export type PhotoUploadFile = { slotId: string; clientFileId: string; filename: string; contentType: string;
  bytes: number; sha256: string; status: 'pending' | 'successful' | 'duplicate' | 'failed' | 'skipped'; error?: { code: string } };
export type ImportDetail = { import: PhotoImport; items: { id: string; status: string; item: Photo }[];
  upload?: { files: PhotoUploadFile[]; canUpload: boolean } };
export type PhotoAccount = { id: string; provider: string; name: string; email: string; needsReauth: boolean; capabilities?: { photos?: boolean } };
export type PhotoDevice = { id: string; name: string };
export type PhotoJourney = { id: string; trip?: { title?: string }; plan?: { title?: string } };
export type PhotoPage = { items: Photo[]; total: number; hasMore: boolean };
export type PhotoSession = { user: { role: string; id: string; householdId?: string; auth_version?: number } | null; csrf?: string | null };
export const CONSENT = 'media-v1';
export const isMediaId = (id: unknown): id is string => typeof id === 'string' && /^[a-f0-9]{24}$/.test(id);
export const terminalImport = (state: string) => ['confirmed', 'cancelled', 'expired', 'failed', 'create_unknown'].includes(state);
export const importLabels: Record<string, string> = {
  queued: '正在准备', creating: '正在连接 Google', waiting_selection: '等待你选择照片或视频',
  listing: '正在读取本次选择', staging: '正在准备预览', awaiting_confirmation: '确认想留下的内容',
  confirmed: '本次保存结果', cancelled: '已取消', expired: '选择已过期', failed: '导入未完成', create_unknown: '连接结果待确认',
};
const errors: Record<string, string> = {
  local_upload_incomplete: '这张照片尚未上传，已跳过；其他成功照片仍可核对保存。',
  input_too_large: '输入图片超过 8 MiB 上限。', unsupported_format: '当前支持内容与类型一致的 JPEG、PNG 和 WebP。',
  invalid_image: '图片不完整或无法安全解码。', multiple_frames: '暂不支持动图或多帧图片。',
  too_many_pixels: '图片像素超过 2000 万像素上限。', output_too_large: '展示图片超过 2 MiB 上限。',
  unsafe_decoder_configuration: '当前解码配置无法安全处理图片。', invalid_input: '照片请求或媒体格式无效。',
  unsupported_type: '此类型暂不支持，已跳过。', unsupported_media: '此媒体格式暂不支持。',
  unsupported_image: '这张照片无法安全生成展示副本。', result_unknown: '旧记录未保存此项的具体处理原因。',
  video_not_ready: 'Google 尚未完成此视频处理或处理失败；其他照片可正常保存，请稍后重新选择此视频。',
  video_invalid_input: '视频字节或媒体类型无效。',
  video_too_large: '视频源文件超过 100 MiB，或展示副本超过 64 MiB 上限。',
  video_too_long: '视频不能超过十分钟，未保存截断片段。',
  video_unsupported: '此视频编码或色彩格式暂不支持。',
  video_invalid: '视频不完整或无法安全解码。',
  video_timeout: '视频处理超时，请稍后重试。',
  video_tools_unavailable: '视频处理服务尚未就绪，请稍后重试。',
  too_large: '所选媒体超过处理上限。', api_disabled: 'Google Photos Picker API 尚未启用，请联系应用维护者；无需重复授权。',
  reauth: '照片来源需要重新授权。', invalid_token: '照片来源需要重新授权。',
  forbidden: '这张照片的读取权限不可用。', selection_changed: 'Google Photos 中的本次选择已变化。',
  selection_limit: '一次最多选择 20 项照片或视频。', expired: '本次临时选择已过期。',
  quota: '照片数量或存储额度已达上限。', network: '连接中断，请稍后刷新核对。',
  timeout: '媒体服务暂时未响应。', rate_limited: '媒体服务繁忙，请稍后核对。',
  unavailable: '照片暂时无法读取。', remote_error: '媒体服务暂时不可用。', worker_error: '照片处理暂时失败。',
  bad_response: '媒体服务响应无法使用。', redirect: '媒体服务返回了不支持的跳转。',
  not_selected: '照片不在本次选择范围内。', not_found: '照片已无法读取。',
  cleanup_unknown: '远端选择器清理结果尚不明确。', create_unknown: '选片页可能已创建，不会自动重复创建。',
};
export const photoError = (code?: string) => errors[code || ''] || '这次处理未完成，请刷新核对；具体原因未记录。';
export const photoSourceLabel = (source?: Photo['source']) => source === 'local-upload' ? '从设备上传' : 'Google Photos';
export const photoOriginalNotice = (source?: Photo['source']) => source === 'local-upload'
  ? '只移除看板展示副本，不修改设备上的原文件；看板不备份原图。' : 'Google Photos 原始内容保留。';
export const countText = (value: number | null | undefined, unit = '张') => Number.isSafeInteger(value) && Number(value) >= 0 ? `${value} ${unit}` : '未记录';
export function savedSummary(value: PhotoImport, unit = '张') {
  const count = value.counts.saved;
  return (count === null ? '本次保存数量未记录' : `已保存 ${count} ${unit}`) + (value.resultsState === 'unknown' ? '；本次其他处理结果未记录' : '');
}
export function previewPath(item: Pick<Photo, 'id' | 'previewUrl'>): string {
  return isMediaId(item.id) && item.previewUrl === `/api/media/items/${item.id}/preview` ? item.previewUrl : '';
}
export function validatePhoto(item: Photo): Photo {
  if (!item || !previewPath(item) || !Number.isSafeInteger(item.revision) || item.revision < 1
    || !['private', 'shared'].includes(item.visibility) || typeof item.canManage !== 'boolean'
    || typeof item.caption !== 'string' || item.caption.length > 500) throw new Error('照片数据已变化，请重新读取。');
  if (item.source !== undefined && !['google-photos', 'local-upload'].includes(item.source)) throw new Error('照片来源无法核对。');
  if (item.mediaType !== undefined && !['photo', 'video'].includes(item.mediaType)) throw new Error('媒体类型无法核对。');
  if (item.mediaType === 'video' && (!videoPath(item) || !Number.isSafeInteger(item.durationMs)
    || item.durationMs! < 1 || item.durationMs! > 600250 || typeof item.hasAudio !== 'boolean')) throw new Error('视频数据已变化，请重新读取。');
  return item;
}

export const MAX_VIDEO_BYTES = 64 * 1024 * 1024;
export class VideoReadBusy extends Error {
  constructor() { super('视频正在读取，请稍后点击播放重试。'); }
}
async function videoIsBusy(response: Response): Promise<boolean> {
  if (response.status !== 503 || response.redirected || response.headers.get('Retry-After') !== '1'
    || response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json'
    || !response.body) return false;
  const reader = response.body.getReader(); let size = 0;
  const parts: Uint8Array[] = [];
  try {
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > 1024) return false;
      parts.push(part.value);
    }
    const raw = new Uint8Array(size); let offset = 0;
    for (const part of parts) { raw.set(part, offset); offset += part.byteLength; }
    const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(raw));
    return value?.code === 'video_busy';
  } catch { return false; }
  finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
export function videoPath(item: Pick<Photo, 'id' | 'mediaType' | 'videoUrl'>): string {
  return item.mediaType === 'video' && isMediaId(item.id) && item.videoUrl === `/api/media/items/${item.id}/video` ? item.videoUrl : '';
}
export function videoDescription(item: Photo): string {
  if (item.mediaType !== 'video') return '';
  validatePhoto(item);
  const seconds = Math.ceil(item.durationMs! / 1000);
  return `视频 · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')} · ${item.hasAudio ? '有声音' : '无声音'}`;
}
// No URL is published before the caller's identity and metadata fence finishes.
// Do not use response.blob(): chunked responses must obey the same hard bound.
export async function fetchMemberVideo(item: Photo, signal: AbortSignal, transport: typeof fetch = fetch): Promise<Blob> {
  validatePhoto(item);
  const path = videoPath(item);
  if (!path) throw new Error('此内容不是可播放的视频。');
  const response = await transport(path, { method: 'GET', mode: 'same-origin', credentials: 'same-origin',
    cache: 'no-store', redirect: 'error', signal, headers: { Accept: 'video/mp4' } });
  if (await videoIsBusy(response)) throw new VideoReadBusy();
  if (!response.ok || response.status !== 200 || response.redirected || response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'video/mp4' || !response.body) {
    await response.body?.cancel(); throw new Error('视频已变化或暂时无法读取，请重新打开详情。');
  }
  const declared = response.headers.get('Content-Length');
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) < 1 || Number(declared) > MAX_VIDEO_BYTES)) {
    await response.body.cancel(); throw new Error('视频大小无法核对。');
  }
  const reader = response.body.getReader(); const chunks: Uint8Array<ArrayBuffer>[] = []; let size = 0;
  try {
    for (;;) {
      if (signal.aborted) throw new Error('视频读取已停止。');
      const part = await reader.read(); if (part.done) break;
      size += part.value.byteLength;
      if (size > MAX_VIDEO_BYTES) throw new Error('视频超过 64 MiB 播放上限。');
      chunks.push(part.value);
    }
    if (signal.aborted || !size || declared !== null && size !== Number(declared)) throw new Error('视频未完整读取。');
    return new Blob(chunks, { type: 'video/mp4' });
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { reader.releaseLock(); }
}
export function validateImport(value: ImportDetail): ImportDetail {
  const row = value?.import;
  if (!row || !isMediaId(row.id) || !Number.isSafeInteger(row.revision) || row.revision < 1
    || !Object.hasOwn(importLabels, row.state) || !['known', 'unknown'].includes(row.resultsState)
    || !Array.isArray(row.results) || row.results.length > 20 || !Array.isArray(value.items) || value.items.length > 20
    || !row.counts || Object.values(row.counts).some(n => n !== null && (!Number.isSafeInteger(n) || n < 0 || n > 20))) {
    throw new Error('选片结果无法核对，请刷新。');
  }
  if (row.source !== undefined && !['google-photos', 'local-upload'].includes(row.source)) throw new Error('选片来源无法核对。');
  const ids = new Set<string>();
  for (const candidate of value.items) {
    validatePhoto(candidate.item);
    if (candidate.id !== candidate.item.id || ids.has(candidate.id) || !['successful', 'duplicate'].includes(candidate.status)) throw new Error('选片清单无法核对，请刷新。');
    ids.add(candidate.id);
  }
  return value;
}
export function newPhotoRequestId(): string {
  // No Math.random fallback: the operation must keep one strong idempotency key.
  if (!globalThis.crypto?.randomUUID) throw new Error('当前环境无法安全建立请求标识，请使用安全连接。');
  return globalThis.crypto.randomUUID();
}
export function confirmPhotos(row: PhotoImport, ids: string[], requestId: string) {
  if (!row.canConfirm || row.state !== 'awaiting_confirmation' || !ids.length || ids.length > 20 || ids.some(id => !isMediaId(id)) || new Set(ids).size !== ids.length) throw new Error('请重新核对要保存的照片。');
  return { revision: row.revision, confirmRequestId: requestId, itemIds: [...ids], consentVersion: CONSENT, persistSelected: true };
}
// HTTP 202 followed by a lost GET must not unlock a new Picker request ID.
export async function finishPhotoCreate(id: string, readImport: (id: string) => Promise<void>, readSources: () => Promise<void>, releaseReceipt: () => void) {
  if (!isMediaId(id)) throw new Error('选片记录无法核对，请保留原请求重试。');
  await readImport(id);
  await readSources();
  releaseReceipt();
}
export const photoSignature = sessionIdentity;
export class PhotoReadDiscarded extends Error {}
// GET permissions are checked separately from component lifetime. Injected I/O
// keeps identity races testable without replacing the business API in browsers.
export class PhotoReadFence {
  private generation = 0;
  private signature: string | undefined;
  private readonly me: () => Promise<PhotoSession>;
  private readonly member: NonNullable<PhotoSession['user']>;
  constructor(me: () => Promise<PhotoSession>, member: NonNullable<PhotoSession['user']>, expected?: string) {
    this.me = me; this.member = member; this.signature = expected;
  }
  invalidate() { this.generation++; }
  async read<T>(load: () => Promise<T>, current: () => boolean): Promise<T> {
    const ticket = this.generation;
    const check = (session: PhotoSession) => {
      if (!current() || ticket !== this.generation) throw new PhotoReadDiscarded();
      const user = session.user;
      if (!user || user.role !== 'member' || user.id !== this.member.id || user.householdId !== this.member.householdId
        || user.auth_version !== this.member.auth_version || (this.signature && photoSignature(session) !== this.signature)) throw new PhotoReadDiscarded('identity');
      this.signature = photoSignature(session);
    };
    check(await this.me());
    const result = await load();
    check(await this.me());
    return result;
  }
}
