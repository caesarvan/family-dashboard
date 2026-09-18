// Shape validation only. The server checks current household membership when
// assigning an owner; old records can still refer to a former member.
export const isMemberId = (value: unknown): value is string =>
  typeof value === 'string' && value !== 'shared' && /^[A-Za-z0-9_-]{1,80}$/.test(value);
export const isOwnerId = (value: unknown): value is string => value === 'shared' || isMemberId(value);
