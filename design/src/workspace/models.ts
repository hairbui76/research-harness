/**
 * Presentation view models for workspace composition.
 *
 * The rail, the shell and the inspector arrange other people's content. They know what a
 * navigation item looks like and how wide a pane is; they know nothing about projects,
 * sessions or research objects beyond the fields below.
 */

import type { IconName } from '../primitives/Icon';

export interface RailItem {
  id: string;
  label: string;
  /** Href when the item is a link; a button when omitted. Both call `onNavigate`. */
  to?: string;
  icon: IconName;
  /** Review inbox size, conflict count, stale count. Rendered as text beside the label. */
  count?: number;
  active?: boolean;
}

export interface ProjectModel {
  id: string;
  name: string;
  /** Absolute path of the workspace on this machine. */
  path?: string;
}

export interface ProviderStatus {
  label: string;
  state: 'ok' | 'degraded' | 'offline' | 'unconfigured';
  detail?: string;
}

/** The six things the research inspector can be showing. */
export type InspectorTab = 'context' | 'evidence' | 'claims' | 'review' | 'conflicts' | 'stale';

export const INSPECTOR_TABS: InspectorTab[] = [
  'context',
  'evidence',
  'claims',
  'review',
  'conflicts',
  'stale',
];

export const INSPECTOR_TAB_META: Record<InspectorTab, { label: string; icon: IconName }> = {
  context: { label: 'Context', icon: 'list' },
  evidence: { label: 'Evidence', icon: 'quote' },
  claims: { label: 'Claims', icon: 'bookmark' },
  review: { label: 'Review inbox', icon: 'inbox' },
  conflicts: { label: 'Conflicts', icon: 'alert-triangle' },
  stale: { label: 'Stale', icon: 'clock' },
};

export const PROVIDER_STATE_META: Record<
  ProviderStatus['state'],
  { label: string; icon: IconName; tone: 'success' | 'warning' | 'error' | 'neutral' }
> = {
  ok: { label: 'Ready', icon: 'circle-check', tone: 'success' },
  degraded: { label: 'Degraded', icon: 'alert-triangle', tone: 'warning' },
  offline: { label: 'Offline', icon: 'wifi-off', tone: 'error' },
  unconfigured: { label: 'Not configured', icon: 'circle-dashed', tone: 'neutral' },
};

/** Where a two-way navigation goes. The application resolves it; this package only emits it. */
export interface InspectorRef {
  /** `evidence`, `claim`, `message`, `attachment`, `manuscript`, `session`, `artifact`, … */
  kind: string;
  id: string;
  /** `rh://` deep link, when the host has one. */
  href?: string;
  label?: string;
}

/** What the inspector is currently following. */
export interface InspectorSelection {
  kind: 'message' | 'reference' | 'attachment' | 'selection';
  /** What the researcher sees: an id, a title, or the selected text. */
  label: string;
  detail?: string;
  /** Where "Open" goes. */
  ref?: InspectorRef;
}

export const SELECTION_KIND_META: Record<
  InspectorSelection['kind'],
  { label: string; icon: IconName }
> = {
  message: { label: 'Message', icon: 'message-square' },
  reference: { label: 'Reference', icon: 'at-sign' },
  attachment: { label: 'Attachment', icon: 'paperclip' },
  selection: { label: 'Selected text', icon: 'quote' },
};

/**
 * Pane sizes as percentages, keyed by pane rather than by position.
 *
 * A plain `number[]` cannot survive collapsing the inspector: the array would have to
 * change length and every pane after the collapsed one would shift. Keying by name lets a
 * surface persist one object and get its layout back whatever is currently visible.
 */
export type PaneSizes = Record<string, number>;

/**
 * Scales the sizes of the currently visible panes so they add up to 100, filling in any
 * pane the caller has no size for with an even share of what is left.
 */
export function resolvePaneSizes(
  sizes: PaneSizes,
  keys: readonly string[],
  fallback: PaneSizes = {},
): number[] {
  if (keys.length === 0) return [];
  const known = keys.map((key) => sizes[key] ?? fallback[key]);
  const specified = known.filter((size): size is number => typeof size === 'number' && size > 0);
  const specifiedTotal = specified.reduce((total, size) => total + size, 0);
  const missing = keys.length - specified.length;
  const share = missing > 0 ? Math.max(0, 100 - specifiedTotal) / missing : 0;
  const filled = known.map((size) => (typeof size === 'number' && size > 0 ? size : share));
  const total = filled.reduce((sum, size) => sum + size, 0);
  if (total <= 0) return keys.map(() => 100 / keys.length);
  return filled.map((size) => (size / total) * 100);
}

/** Writes an array of pane sizes back onto the keyed record it came from. */
export function mergePaneSizes(
  previous: PaneSizes,
  keys: readonly string[],
  next: readonly number[],
): PaneSizes {
  const merged: PaneSizes = { ...previous };
  keys.forEach((key, index) => {
    const size = next[index];
    if (typeof size === 'number') merged[key] = size;
  });
  return merged;
}
