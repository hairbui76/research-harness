/**
 * The pure view mapping: the daemon's enums become a tone and a word, and the report
 * becomes two groups. Nothing here decides whether a runtime may be used — `routable` and
 * `unavailable_reason` are the daemon's own fields (spec §18).
 */
import { describe, expect, it } from 'vitest';
import scan from '../../test/fixtures/providers/cli-scan.json';
import type { CliRuntimeStatus, CliScanReport } from '../../api/dto';
import { configuredFor, defaultEntryName, groupRuntimes, runtimeBadges } from './mappers';

const report = scan as unknown as CliScanReport;

function runtime(name: string): CliRuntimeStatus {
  const found = report.runtimes.find((item) => item.runtime === name);
  if (!found) throw new Error(`the fixture has no ${name} runtime`);
  return found;
}

describe('runtime badges', () => {
  it('names login, bounded mode, and compatibility with a tone and a word', () => {
    expect(runtimeBadges(runtime('codex'))).toEqual({
      login: { tone: 'success', label: 'Logged in' },
      bounded: { tone: 'success', label: 'Bounded mode' },
      compatibility: { tone: 'success', label: 'Verified 0.150.1' },
    });
    expect(runtimeBadges(runtime('claude')).login).toEqual({
      tone: 'error',
      label: 'Not logged in',
    });
    expect(runtimeBadges(runtime('cursor-agent')).bounded).toEqual({
      tone: 'error',
      label: 'No bounded mode',
    });
    expect(runtimeBadges(runtime('cursor-agent')).compatibility).toEqual({
      tone: 'warning',
      label: 'Untested 1.4.0',
    });
    expect(runtimeBadges(runtime('amp')).login).toEqual({
      tone: 'neutral',
      label: 'Login unverified',
    });
  });

  it('says a bounded mode is unproven, not absent, when the daemon could not prove one', () => {
    expect(runtimeBadges(runtime('opencode')).bounded).toEqual({
      tone: 'warning',
      label: 'Bounded mode unproven',
    });
    expect(runtimeBadges(runtime('opencode')).compatibility).toEqual({
      tone: 'warning',
      label: 'Untested 1.18.0',
    });
  });

  it('falls back to the daemon having reported no version', () => {
    expect(runtimeBadges(runtime('amp')).compatibility).toEqual({
      tone: 'neutral',
      label: 'Version unknown',
    });
  });
});

describe('grouping', () => {
  it('splits installed from unavailable and keeps registry order', () => {
    const groups = groupRuntimes(report);
    expect(groups.installed.map((item) => item.runtime)).toEqual([
      'codex',
      'claude',
      'cursor-agent',
      'opencode',
    ]);
    expect(groups.unavailable.map((item) => item.runtime)).toEqual([
      'amp',
      'deepseek-harness',
      'pi',
    ]);
  });

  it('groups on installation alone, so a not-routable installed CLI still shows its state', () => {
    const groups = groupRuntimes(report);
    const opencode = groups.installed.find((item) => item.runtime === 'opencode');
    expect(opencode?.routable).toBe(false);
    expect(opencode?.unavailable_reason).toBe(
      'opencode 1.18.0 could not prove a bounded (no-tools, read-only) mode',
    );
  });

  it('finds the configured entry for a runtime', () => {
    expect(configuredFor(report, 'codex')?.name).toBe('codex-sub');
    expect(configuredFor(report, 'claude')).toBeNull();
    expect(defaultEntryName('deepseek-harness')).toBe('deepseek-harness-subscription');
  });
});
