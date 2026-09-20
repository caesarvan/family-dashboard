import type { CalendarEvent, Member } from './types';

export type CalendarVisibility = 'private' | 'shared';

/** Presentation/write intent only. The server filters every read and checks ACL. */
export function calendarPrivacy(event?: CalendarEvent, user?: Member | null) {
  if (!event) return { visibility: 'private' as CalendarVisibility, canChange: user?.role === 'member',
    notice: '仅你可见，其他家庭成员和电视不可见。' };
  if (event.visibility === undefined && event.createdBy === undefined) return {
    visibility: 'shared' as CalendarVisibility, canChange: false,
    notice: event.sync ? '同步日程沿用已选择来源的共享范围。' : event.journeyId || event.travelTiming
      ? '旅行日程沿用家庭共享范围。' : '原有日程保持家庭共享；新建安排可选择仅自己。',
  };
  if (!['private', 'shared'].includes(event.visibility || '') || typeof event.createdBy !== 'string' || !event.createdBy.trim()) return {
    visibility: null, canChange: false, notice: '暂时无法读取日程可见范围，请关闭并刷新后核对。',
  };
  return { visibility: event.visibility as CalendarVisibility,
    canChange: !event.sync && !event.travelTiming && user?.role === 'member' && event.createdBy === user.id,
    notice: event.visibility === 'private' ? '仅你可见，其他家庭成员和电视不可见。' : '家庭成员和电视可见；只有创建者可以收回共享。',
  };
}

export function calendarPrivacyPayload(event: CalendarEvent | undefined, user: Member | null | undefined,
  visibility: CalendarVisibility): { visibility?: CalendarVisibility } {
  const scope = calendarPrivacy(event, user);
  if (!scope.visibility) throw new Error(scope.notice);
  if (!['private', 'shared'].includes(visibility)) throw new Error('请选择日程可见范围');
  if (!event && user?.role !== 'member') throw new Error('请先使用成员账户登录');
  if (scope.canChange) return { visibility };
  if (visibility !== scope.visibility) throw new Error('只有创建者可以修改这条安排的可见范围');
  return {}; // Never infer or send createdBy; preserve old/cloud/other-member scope.
}

export const calendarVisibilityLabel = (event: CalendarEvent): string => {
  const visibility = calendarPrivacy(event).visibility;
  return visibility === 'private' ? '仅自己' : visibility === 'shared' ? '家庭共享' : '可见范围待核对';
};
