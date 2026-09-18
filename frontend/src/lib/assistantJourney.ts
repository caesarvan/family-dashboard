import type { Member } from './types';

/** Matches the existing local-search prefixes accepted by /assistant/plan. */
export function isAssistantSearchRequest(prompt: string): boolean {
  return /^(?:搜索|查找|找一下)/.test(prompt.trim());
}

export function assistantPlanOptions(prompt: string, useModel: boolean, includeHouseholdContext: boolean) {
  const enabled = useModel && !isAssistantSearchRequest(prompt);
  return { useModel: enabled, includeHouseholdContext: enabled && includeHouseholdContext };
}

/** A search hit supplies only a trip entity ID, never an editable plan. */
export function assistantTripRequest(match: { kind: unknown; id: unknown }, key: number): { key: number; id: string } | null {
  return match.kind === 'trips' && typeof match.id === 'string' && /^[a-f0-9]{24}$/.test(match.id)
    && Number.isSafeInteger(key) && key > 0 ? { key, id: match.id } : null;
}

/** Explicit list/search commands retain precedence over words inside the request. */
export function isJourneyRequest(prompt: string): boolean {
  const text = prompt.trim();
  return !isAssistantSearchRequest(text) && !/^(待办|采购)\s*[:：]/.test(text)
    && /(旅行|行程|旅游|出发日期|返程日期)/.test(text);
}

export function journeySessionKey(session: { user: Member | null; csrf?: string | null }): string {
  const user = session.user;
  return JSON.stringify([user?.role, user?.householdId, user?.id, user?.auth_version, session.csrf]);
}
