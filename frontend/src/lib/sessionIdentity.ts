/** One identity key for the provider and every asynchronous read/write fence. */
export type IdentitySession = {
  user: {
    role: string; id: string; householdId?: string; auth_version?: number;
    membershipRevision?: number; accountId?: string; accountAuthVersion?: number;
    authenticationGeneration?: number;
  } | null;
  csrf?: string | null;
};

export function sessionIdentity(session: IdentitySession): string {
  const user = session.user;
  return JSON.stringify([user?.role, user?.householdId, user?.id, user?.auth_version,
    user?.membershipRevision, user?.accountId, user?.accountAuthVersion,
    user?.authenticationGeneration, session.csrf]);
}
