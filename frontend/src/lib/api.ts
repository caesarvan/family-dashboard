export class ApiError extends Error {
  constructor(message: string, public status = 0, public code = '') { super(message); }
}

export async function request<T>(path: string, options: RequestInit = {}, csrf = ''): Promise<T> {
  const origin = (process.env.EXPO_PUBLIC_API_ORIGIN || '').replace(/\/$/, '');
  let response: Response;
  try {
    response = await fetch(origin + '/api' + path, {
      ...options, credentials: 'include', cache: 'no-store',
      headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}), ...options.headers },
    });
  } catch { throw new ApiError('连接中断，请检查网络'); }
  let value: any;
  try { value = await response.json(); }
  catch { throw new ApiError('暂时无法确认服务返回的结果，请刷新核对', response.ok ? 0 : response.status); }
  if (!response.ok) throw new ApiError(value.error || '暂时无法完成操作', response.status, value.code || '');
  return value as T;
}
