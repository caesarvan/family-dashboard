import type { ListItem } from './types';

export const dependencyLimit = 20;
export function dependencyIds(item: Pick<ListItem, 'dependsOn'>): string[] {
  const ids = item.dependsOn;
  if (ids === undefined) return [];
  if (!Array.isArray(ids) || ids.length > dependencyLimit || ids.some(id => typeof id !== 'string' || !id || id.length > 128) || new Set(ids).size !== ids.length)
    throw new Error('前置事项格式无法核对，请刷新清单后重试。');
  return [...ids];
}

/** Advisory current-state projection; the server always rechecks on save. */
export function dependencyInfo(item: ListItem, tasks: ListItem[], byId = new Map(tasks.map(task => [task.id, task]))): { blocked: boolean; message: string } {
  if (item.done) return { blocked: false, message: '' };
  try {
    const ids = dependencyIds(item);
    const blocked = ids.filter(id => !byId.get(id)?.done || byId.get(id)?.sync);
    if (blocked.length) return { blocked: true, message: '先完成：' + blocked.map(id => byId.get(id)?.title || '已失效的前置事项').join('、') };
    if (item.dependencyStatus === 'blocked' || (Array.isArray(item.blockedBy) && item.blockedBy.length))
      return { blocked: true, message: '前置事项状态需要核对，请刷新清单。' };
    return { blocked: false, message: ids.length ? '前置事项已完成' : '' };
  } catch {
    return { blocked: true, message: '前置事项格式无法核对，请刷新清单。' };
  }
}

export function dependencyStates(tasks: ListItem[]): Map<string, ReturnType<typeof dependencyInfo>> {
  const byId = new Map(tasks.map(task => [task.id, task]));
  return new Map(tasks.map(task => [task.id, dependencyInfo(task, tasks, byId)]));
}

export function dependencyCreatesCycle(currentId: string | undefined, candidateId: string, tasks: ListItem[]): boolean {
  if (!currentId) return false;
  const byId = new Map(tasks.map(task => [task.id, task])), pending = [candidateId], seen = new Set<string>();
  while (pending.length) {
    const id = pending.pop()!;
    if (id === currentId) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    const item = byId.get(id);
    if (item) { try { pending.push(...dependencyIds(item)); } catch { return true; } }
  }
  return false;
}

/** Compute the unavailable choices once, including every dependent of this task. */
export function unavailableDependencyIds(currentId: string | undefined, tasks: ListItem[]): Set<string> {
  const reverse = new Map<string, string[]>(), pending = currentId ? [currentId] : [];
  for (const task of tasks) {
    try { for (const id of dependencyIds(task)) { const children = reverse.get(id); if (children) children.push(task.id); else reverse.set(id, [task.id]); } }
    catch { pending.push(task.id); }
  }
  const unavailable = new Set<string>();
  while (pending.length) {
    const id = pending.pop()!;
    if (unavailable.has(id)) continue;
    unavailable.add(id); pending.push(...(reverse.get(id) || []));
  }
  return unavailable;
}

export function dependencyPayload(ids: string[], tasks: ListItem[], currentId?: string): string[] {
  const value = dependencyIds({ dependsOn: ids });
  const byId = new Map(tasks.map(task => [task.id, task]));
  for (const id of value) {
    if (!byId.has(id) || byId.get(id)?.sync) throw new Error('前置事项已失效或来自同步清单，请先取消选择并核对。');
    if (dependencyCreatesCycle(currentId, id, tasks)) throw new Error('这些事项会互相等待，请调整前置事项。');
  }
  return value;
}
