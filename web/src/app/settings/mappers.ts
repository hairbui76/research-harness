/**
 * Pure view mapping for the Models & providers settings. Words and tones only; the
 * daemon decided every state (PRODUCT §5 P10, spec §18).
 *
 * There is deliberately no `routable()` and no `unavailableReason()` here. Whether a
 * runtime may be routed to, and which gate failed, are runtime/safety rules the daemon
 * publishes on `CliRuntimeStatus` as `routable` and `unavailable_reason`; a second copy of
 * that arithmetic in the browser would be a second answer, and the cockpit is only allowed
 * to render the daemon's.
 */
import type { BadgeTone } from '@research-harness/design';
import type { CliRuntimeStatus, CliScanReport, ConfiguredCliProviderView } from '../../api/dto';

export interface BadgeView {
  tone: BadgeTone;
  label: string;
}

export interface RuntimeBadges {
  login: BadgeView;
  bounded: BadgeView;
  compatibility: BadgeView;
}

/**
 * The three gates the daemon reports, each as one tone and one word.
 *
 * The word always carries the state, so the badge never signals with colour alone
 * (DS spec §12.6), and the version is named wherever the gate is about a version.
 */
export function runtimeBadges(status: CliRuntimeStatus): RuntimeBadges {
  const version = status.version;

  const login: BadgeView =
    status.auth_status === 'ok'
      ? { tone: 'success', label: 'Logged in' }
      : status.auth_status === 'missing'
        ? { tone: 'error', label: 'Not logged in' }
        : { tone: 'neutral', label: 'Login unverified' };

  const bounded: BadgeView =
    status.bounded_mode === 'safe'
      ? { tone: 'success', label: 'Bounded mode' }
      : status.bounded_mode === 'unsupported'
        ? { tone: 'error', label: 'No bounded mode' }
        : { tone: 'warning', label: 'Bounded mode unproven' };

  const compatibility: BadgeView =
    version === null
      ? { tone: 'neutral', label: 'Version unknown' }
      : status.compatibility === 'verified'
        ? { tone: 'success', label: `Verified ${version}` }
        : status.compatibility === 'blocked'
          ? { tone: 'error', label: `Incompatible ${version}` }
          : status.compatibility === 'warning'
            ? { tone: 'warning', label: `Untested ${version}` }
            : { tone: 'neutral', label: `Untested ${version}` };

  return { login, bounded, compatibility };
}

/**
 * The two groups the tab shows.
 *
 * The split is on installation, not on routability: an installed CLI that the daemon will
 * not route to (no proven bounded mode, a stale login) still belongs beside the ones that
 * work, because its card is where the researcher reads why and what to do about it.
 * `report.runtimes` arrives in registry order and both groups keep it.
 */
export function groupRuntimes(report: CliScanReport): {
  installed: CliRuntimeStatus[];
  unavailable: CliRuntimeStatus[];
} {
  return {
    installed: report.runtimes.filter((item) => item.available),
    unavailable: report.runtimes.filter((item) => !item.available),
  };
}

/** The `local_cli` entry already in research.yaml for this runtime, if there is one. */
export function configuredFor(
  report: CliScanReport,
  runtime: string,
): ConfiguredCliProviderView | null {
  return report.configured.find((item) => item.runtime === runtime) ?? null;
}

/** The name the form proposes for a first entry; the researcher may replace it. */
export function defaultEntryName(runtime: string): string {
  return `${runtime}-subscription`;
}
