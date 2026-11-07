// Usage allowances shown to invited people and operators (ADR 0058).
export type Kind = "image" | "voice" | "assistant" | "release" | "training" | "music";
export type Limits = Partial<Record<Kind, { daily?: number; total?: number }>>;
export type Usage = Partial<Record<Kind, { day: number; total: number }>>;

export const KINDS: Array<[Kind, string]> = [
  ["image", "Images"], ["voice", "Voice lines"], ["assistant", "Assistant replies"],
  ["release", "Release builds"], ["training", "Training runs"], ["music", "Music tracks"],
];

export interface UsageRow { kind: Kind; label: string; day: number; daily?: number; total: number; totalLimit?: number }

export function usageRows(limits: Limits | null, usage: Usage): UsageRow[] {
  return KINDS.map(([kind, label]) => ({
    kind, label, day: usage[kind]?.day ?? 0, total: usage[kind]?.total ?? 0,
    daily: limits?.[kind]?.daily, totalLimit: limits?.[kind]?.total,
  }));
}

export function amount(used: number, limit: number | undefined): string {
  if (limit === undefined) return `${used}`;
  return limit === 0 ? "not included" : `${used} of ${limit}`;
}

export type InvitationState = "active" | "used" | "expired" | "revoked";

export function invitationState(
  invitation: { revoked_at: string | null; expires_at: string | null; redemption_count: number; max_redemptions: number },
  now = Date.now(),
): InvitationState {
  if (invitation.revoked_at) return "revoked";
  if (invitation.expires_at && Date.parse(invitation.expires_at) <= now) return "expired";
  return invitation.redemption_count >= invitation.max_redemptions ? "used" : "active";
}

/** Limits typed into the form: blank means "no limit"; anything else must be a whole number. */
export function parseLimits(form: Record<string, string>): Limits | string {
  const limits: Limits = {};
  for (const [kind, label] of KINDS) {
    const entry: { daily?: number; total?: number } = {};
    for (const window of ["daily", "total"] as const) {
      const text = (form[`${kind}.${window}`] ?? "").trim();
      if (!text) continue;
      if (!/^\d{1,8}$/.test(text)) return `${label}: use a whole number, or leave it blank for no limit.`;
      entry[window] = Number(text);
    }
    if (Object.keys(entry).length) limits[kind] = entry;
  }
  return limits;
}

export function limitsForm(limits: Limits): Record<string, string> {
  const form: Record<string, string> = {};
  for (const [kind] of KINDS) {
    for (const window of ["daily", "total"] as const) {
      const value = limits[kind]?.[window];
      form[`${kind}.${window}`] = value === undefined ? "" : String(value);
    }
  }
  return form;
}

export function invitationMessage(link: string, key: string | null): string {
  return key
    ? `You're invited to try FlintGraph, a studio for visual novels.\n\nOpen ${link} , sign in with any account and enter this key:\n${key}`
    : `You're invited to try FlintGraph, a studio for visual novels.\n\nOpen ${link} and sign in with this email address to join.`;
}
