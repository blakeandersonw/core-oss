import type { ProfileStatus } from "../stores/authStore";

export type BootstrapGate = "ready" | "loading" | "profile-error";

interface BootstrapGateInput {
  isAuthenticated: boolean;
  authLoading: boolean;
  onboardingCompletedAt: string | null | undefined;
  profileStatus: ProfileStatus;
  isInviteRoute: boolean;
  isShareLinkRoute: boolean;
}

export function resolveBootstrapGate({
  isAuthenticated,
  authLoading,
  onboardingCompletedAt,
  profileStatus,
  isInviteRoute,
  isShareLinkRoute,
}: BootstrapGateInput): BootstrapGate {
  if (!isAuthenticated || isInviteRoute || isShareLinkRoute) return "ready";
  if (authLoading) return "loading";
  if (onboardingCompletedAt !== undefined) return "ready";
  if (profileStatus === "loading") return "loading";
  if (profileStatus === "error") return "profile-error";
  return "loading";
}
