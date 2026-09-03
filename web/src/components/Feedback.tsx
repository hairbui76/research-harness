/**
 * The presentation every research page shares, expressed in the Design System.
 *
 * Nothing here is a new primitive: `Loading`/`Empty` are `AsyncState`, `ErrorBox` is
 * `ErrorNotice`, `Panel` is a `Card`, and `StatusBadge` is `AuthorityBadge` when the word
 * the daemon used *is* an authority label and a toned `Badge` otherwise. They exist so
 * that eleven views spell the same thing the same way, not to re-implement anything the
 * package owns (DS spec §12.7).
 *
 * `StatusBadge` never signals with colour alone: every badge renders the daemon's own word
 * beside its glyph (DS spec §12.6).
 */
import type { ReactNode } from 'react';
import {
  AsyncState,
  AuthorityBadge,
  Badge,
  Card,
  ErrorNotice,
  ScrollArea,
  AUTHORITY_LABELS,
} from '@research-harness/design';
import type { AuthorityLabel, BadgeProps, IconName } from '@research-harness/design';

export function Loading({ what }: { what: string }) {
  return <AsyncState kind="loading" title={`Reading ${what}…`} />;
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <ErrorNotice
      kind={retry ? 'retryable' : 'fatal'}
      title="The daemon refused or could not answer"
      description={error}
      safety={{ source: 'safe' }}
      {...(retry ? { actions: [{ label: 'Try again', onClick: retry, iconStart: 'refresh-cw' }] } : {})}
    />
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <AsyncState kind="empty" title={children} />;
}

export function Panel({
  title,
  action,
  children,
}: {
  title: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card
      as="section"
      header={
        <>
          <h2 className="rh-text-h3">{title}</h2>
          {action}
        </>
      }
    >
      <div className="rh-web-stack rh-web-stack--tight">{children}</div>
    </Card>
  );
}

/** A definition row: the label the daemon uses, and the value it reported. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rh-web-field">
      <dt className="rh-text-label">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

/** Wraps a run of `Field`s in the definition list they belong to. */
export function Fields({ children }: { children: ReactNode }) {
  return <dl className="rh-web-fields">{children}</dl>;
}

/**
 * A research table: compact density, and a horizontally scrollable region that is
 * keyboard-reachable and named once it actually scrolls (WCAG 2.2 2.5.7 / 2.1.1).
 */
export function DataTable({
  label,
  head,
  children,
}: {
  label: string;
  head: ReactNode;
  children: ReactNode;
}) {
  return (
    <div data-density="compact">
      <ScrollArea orientation="horizontal" label={label}>
        <table className="rh-web-table">
          <thead>{head}</thead>
          <tbody>{children}</tbody>
        </table>
      </ScrollArea>
    </div>
  );
}

function isAuthority(value: string): value is AuthorityLabel {
  return (AUTHORITY_LABELS as readonly string[]).includes(value);
}

/**
 * Which authority badge a v1.0 object's status draws.
 *
 * This is presentation, not judgement: the daemon's own word is always rendered beside the
 * badge (a `ClaimCard` prints `status`; a table prints the cell), and nothing here changes
 * what the object is. The mapping exists because the Design System speaks the v1.1
 * `AuthorityLabel` vocabulary (plan §0.3) and the v1.0 claim assessment does not — until
 * the ResearchGraph carries `authority` on every node, this is where the two meet.
 *
 * `stale` wins, because a stale object's authority is the thing a researcher must not rely
 * on (ADR-008).
 */
export function authorityOf(status: string, stale?: boolean): AuthorityLabel {
  if (stale) return 'stale';
  if (isAuthority(status)) return status;
  if (status === 'supported' || status === 'accepted') return 'accepted';
  if (status === 'unsupported') return 'contested';
  return 'candidate';
}

/**
 * How the daemon's vocabularies read as feedback tone.
 *
 * The six `AuthorityLabel`s are not in here on purpose — they go to `AuthorityBadge`,
 * which owns their presentation. What is left is the review queue's categories, the
 * verifier's verdicts, screening states and anchor verdicts: application feedback about an
 * object, not a statement of its scientific authority.
 */
const TONES: Record<string, BadgeProps['tone']> = {
  conflict: 'error',
  unsupported: 'error',
  error: 'error',
  missing: 'error',
  contradicted: 'error',
  high_risk: 'warning',
  ambiguous: 'warning',
  warning: 'warning',
  relocated: 'warning',
  partially_supported: 'warning',
  unverified: 'warning',
  supported: 'success',
  verified: 'success',
  valid: 'success',
  included: 'success',
  routine: 'neutral',
  info: 'info',
};

const ICONS: Record<string, IconName> = {
  conflict: 'alert-triangle',
  unsupported: 'circle-x',
  error: 'alert-circle',
  missing: 'link-2-off',
  high_risk: 'alert-triangle',
  ambiguous: 'circle-help',
  relocated: 'arrow-right',
  partially_supported: 'info',
  unverified: 'circle-dashed',
  supported: 'circle-check',
  verified: 'circle-check',
  valid: 'circle-check',
  routine: 'list',
};

export interface StatusBadgeProps {
  /** The daemon's own word. Rendered verbatim unless `children` replaces it. */
  status: string;
  size?: 'sm' | 'md';
  children?: ReactNode;
}

export function StatusBadge({ status, size = 'sm', children }: StatusBadgeProps) {
  if (isAuthority(status)) {
    return (
      <AuthorityBadge
        authority={status}
        size={size}
        {...(children === undefined ? {} : { label: children })}
      />
    );
  }
  const icon = ICONS[status];
  return (
    <Badge tone={TONES[status] ?? 'neutral'} size={size} {...(icon ? { icon } : { icon: null })}>
      {children ?? status}
    </Badge>
  );
}
