// Local media contracts. Provider URLs never become preview image sources.
export type Photo = {
  id: string; revision: number; caption: string; width: number; height: number;
  previewUrl: string; visibility: 'private' | 'shared'; canManage: boolean; createdAt: string;
  journey: { id: string; tripId: string; title: string } | null;
  accountId?: string; displayFilename?: string;
};
export type PhotoImport = {
  id: string; revision: number; state: string; createdAt: string; expiresAt: string;
  nextPollAt: string | null; canConfirm: boolean; pickerUri?: string;
  resultsState: 'known' | 'unknown';
  counts: Record<'selected' | 'ready' | 'failed' | 'skipped' | 'pending' | 'saved' | 'unselected', number | null>;
  results: { position: number; status: string; error?: { code: string } }[];
  error?: { code: string }; cleanupPending: boolean;
};
export type ImportDetail = { import: PhotoImport; items: { id: string; status: string; item: Photo }[] };
export type PhotoAccount = { id: string; provider: string; name: string; email: string; needsReauth: boolean; capabilities?: { photos?: boolean } };
export type PhotoDevice = { id: string; name: string };
export type PhotoJourney = { id: string; trip?: { title?: string }; plan?: { title?: string } };
export type PhotoPage = { items: Photo[]; total: number; hasMore: boolean };
export type PhotoSession = { user: { role: string; id: string; householdId?: string; auth_version?: number } | null; csrf?: string | null };
export const CONSENT = 'media-v1';
export const isMediaId = (id: unknown): id is string => typeof id === 'string' && /^[a-f0-9]{24}$/.test(id);
export const terminalImport = (state: string) => ['confirmed', 'cancelled', 'expired', 'failed', 'create_unknown'].includes(state);
export const importLabels: Record<string, string> = {
  queued: '正在准备', creating: '正在连接 Google', waiting_selection: '等待你选择照片',
  listing: '正在读取本次选择', staging: '正在准备预览', awaiting_confirmation: '确认想留下的照片',
  confirmed: '本次保存结果', cancelled: '已取消', expired: '选择已过期', failed: '导入未完成', create_unknown: '连接结果待确认',
};
const errors: Record<string, string> = {
  input_too_large: '输入图片超过 8 MiB 上限。', unsupported_format: '当前支持内容与类型一致的 JPEG、PNG 和 WebP。',
  invalid_image: '图片不完整或无法安全解码。', multiple_frames: '暂不支持动图或多帧图片。',
  too_many_pixels: '图片像素超过 2000 万像素上限。', output_too_large: '展示图片超过 2 MiB 上限。',
  unsafe_decoder_configuration: '当前解码配置无法安全处理图片。', invalid_input: '照片请求或媒体格式无效。',
  unsupported_type: '本次只处理照片，已跳过非照片媒体。', unsupported_media: '此媒体格式暂不支持。',
  unsupported_image: '这张照片无法安全生成展示副本。', result_unknown: '旧记录未保存此项的具体处理原因。',
  too_large: '所选媒体超过处理上限。', api_disabled: 'Google Photos Picker API 尚未启用，请联系应用维护者；无需重复授权。',
  reauth: '照片来源需要重新授权。', invalid_token: '照片来源需要重新授权。',
  forbidden: '这张照片的读取权限不可用。', selection_changed: 'Google Photos 中的本次选择已变化。',
  selection_limit: '一次最多选择 20 张照片。', expired: '本次临时选择已过期。',
  quota: '照片数量或存储额度已达上限。', network: '连接中断，请稍后刷新核对。',
  timeout: '媒体服务暂时未响应。', rate_limited: '媒体服务繁忙，请稍后核对。',
  unavailable: '照片暂时无法读取。', remote_error: '媒体服务暂时不可用。', worker_error: '照片处理暂时失败。',
  bad_response: '媒体服务响应无法使用。', redirect: '媒体服务返回了不支持的跳转。',
  not_selected: '照片不在本次选择范围内。', not_found: '照片已无法读取。',
  cleanup_unknown: '远端选择器清理结果尚不明确。', create_unknown: '选片页可能已创建，不会自动重复创建。',
};
export const photoError = (code?: string) => errors[code || ''] || '这次处理未完成，请刷新核对；具体原因未记录。';
export const countText = (value: number | null | undefined) => Number.isSafeInteger(value) && Number(value) >= 0 ? `${value} 张` : '未记录';
export function savedSummary(value: PhotoImport) {
  const count = value.counts.saved;
  return (count === null ? '本次保存数量未记录' : `已保存 ${count} 张`) + (value.resultsState === 'unknown' ? '；本次其他处理结果未记录' : '');
}
export function previewPath(item: Pick<Photo, 'id' | 'previewUrl'>): string {
  return isMediaId(item.id) && item.previewUrl === `/api/media/items/${item.id}/preview` ? item.previewUrl : '';
}
export function validatePhoto(item: Photo): Photo {
  if (!item || !previewPath(item) || !Number.isSafeInteger(item.revision) || item.revision < 1
    || !['private', 'shared'].includes(item.visibility) || typeof item.canManage !== 'boolean'
    || typeof item.caption !== 'string' || item.caption.length > 500) throw new Error('照片数据已变化，请重新读取。');
  return item;
}
export function validateImport(value: ImportDetail): ImportDetail {
  const row = value?.import;
  if (!row || !isMediaId(row.id) || !Number.isSafeInteger(row.revision) || row.revision < 1
    || !Object.hasOwn(importLabels, row.state) || !['known', 'unknown'].includes(row.resultsState)
    || !Array.isArray(row.results) || row.results.length > 20 || !Array.isArray(value.items) || value.items.length > 20
    || !row.counts || Object.values(row.counts).some(n => n !== null && (!Number.isSafeInteger(n) || n < 0 || n > 20))) {
    throw new Error('选片结果无法核对，请刷新。');
  }
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
export const photoSignature = (session: PhotoSession) => JSON.stringify([session.user?.role, session.user?.householdId, session.user?.id, session.user?.auth_version, session.csrf]);
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
