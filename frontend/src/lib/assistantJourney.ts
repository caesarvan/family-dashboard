import type { Member } from './types';
import { sessionIdentity } from './sessionIdentity.ts';

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
export function isExistingTripChangeRequest(prompt: string): boolean {
  const text = prompt.trim();
  return !isAssistantSearchRequest(text) && !/^(待办|采购|任务)\s*[:：]/.test(text)
    && /(旅行|行程|旅游|出发|返程)/.test(text)
    && /(推迟|延后|延迟|后移|提前|前移|改期|改到|改为|移到|挪到|调整到|调整为)/.test(text);
}

export function isJourneyRequest(prompt: string): boolean {
  const text = prompt.trim();
  return !isAssistantSearchRequest(text) && !isExistingTripChangeRequest(text) && !isJourneyStatusRequest(text) && !/^(待办|采购|任务)\s*[:：]/.test(text)
    && /(旅行|行程|旅游|出发日期|返程日期)/.test(text);
}

const statusPhrase = /(?:准备得怎么样|准备怎么样|准备情况|准备进度|还有什么没办|还有哪些没办|还有什么没做|还有哪些没做|还有什么未完成|还有哪些未完成)/;
/** Explicit writes keep their original entry; mixed read/write wording is clarified locally. */
export function isJourneyStatusRequest(prompt: string): boolean {
  const text = prompt.trim();
  return !isAssistantSearchRequest(text) && !isExistingTripChangeRequest(text) && !/^(待办|采购|任务)\s*[:：]/.test(text)
    && /(旅行|行程|旅游)/.test(text) && statusPhrase.test(text);
}
export function journeyStatusIntent(prompt: string): { query: string; clarification: string } {
  const text = prompt.trim();
  if (statusPhrase.test(text) && /(?:新建|创建|新增|添加|删除|取消|帮我完成|标记完成|改成|改为|改到|推迟|提前|改期)/.test(text))
    return { query: '', clarification: '这句话同时包含查询和修改。请只描述要查询的旅行；修改请从原旅行处理。' };
  const match = text.match(/^(.*?)(?:准备得怎么样|准备怎么样|准备情况|准备进度|还有什么没办|还有哪些没办|还有什么没做|还有哪些没做|还有什么未完成|还有哪些未完成)[？?。！!\s]*$/);
  const query = (match ? match[1].replace(/(?:旅行|行程|旅游)\s*$/, '') : '').trim();
  return { query: Array.from(query).length <= 100 ? query : '', clarification: match && Array.from(query).length <= 100 ? '' : '请在下方填写旅行关键词，或留空选择已有旅行。' };
}

export function journeySessionKey(session: { user: Member | null; csrf?: string | null }): string {
  return sessionIdentity(session);
}
