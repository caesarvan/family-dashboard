import type { Member } from './types';

/** Explicit list/search commands retain precedence over words inside the request. */
export function isJourneyRequest(prompt: string): boolean {
  const text = prompt.trim();
  return !/^(待办|采购|搜索)\s*[:：]/.test(text)
    && /(旅行|行程|旅游|出发日期|返程日期)/.test(text);
}

export function journeySessionKey(session: { user: Member | null; csrf?: string | null }): string {
  const user = session.user;
  return JSON.stringify([user?.role, user?.householdId, user?.id, user?.auth_version, session.csrf]);
}
