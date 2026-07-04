import assert from "node:assert/strict";
import { resolveBootstrapGate } from "../src/lib/bootstrapRouting.ts";

const base = {
  isAuthenticated: true,
  authLoading: false,
  onboardingCompletedAt: undefined,
  profileStatus: "idle",
  isInviteRoute: false,
  isShareLinkRoute: false,
};

const cases = [
  {
    name: "authenticated unknown onboarding while auth is loading shows loading",
    input: { ...base, authLoading: true },
    expected: "loading",
  },
  {
    name: "authenticated unknown onboarding while profile is loading shows loading",
    input: { ...base, profileStatus: "loading" },
    expected: "loading",
  },
  {
    name: "authenticated unknown onboarding after profile failure shows retry error",
    input: { ...base, profileStatus: "error" },
    expected: "profile-error",
  },
  {
    name: "authenticated missing onboarding timestamp is ready for onboarding redirect",
    input: { ...base, onboardingCompletedAt: null, profileStatus: "ready" },
    expected: "ready",
  },
  {
    name: "authenticated completed onboarding is ready for app routing",
    input: { ...base, onboardingCompletedAt: "2026-07-04T12:00:00.000Z", profileStatus: "ready" },
    expected: "ready",
  },
  {
    name: "known onboarding status stays ready during later profile refresh",
    input: { ...base, onboardingCompletedAt: "2026-07-04T12:00:00.000Z", profileStatus: "loading" },
    expected: "ready",
  },
  {
    name: "known onboarding status stays ready after later profile failure",
    input: { ...base, onboardingCompletedAt: "2026-07-04T12:00:00.000Z", profileStatus: "error" },
    expected: "ready",
  },
  {
    name: "signed-out bootstrap does not block landing routing",
    input: { ...base, isAuthenticated: false, authLoading: true },
    expected: "ready",
  },
  {
    name: "invite routes bypass app bootstrap gate",
    input: { ...base, profileStatus: "error", isInviteRoute: true },
    expected: "ready",
  },
  {
    name: "share routes bypass app bootstrap gate",
    input: { ...base, profileStatus: "error", isShareLinkRoute: true },
    expected: "ready",
  },
];

for (const testCase of cases) {
  assert.equal(resolveBootstrapGate(testCase.input), testCase.expected, testCase.name);
}

console.log(`bootstrap routing checks passed (${cases.length} cases)`);
