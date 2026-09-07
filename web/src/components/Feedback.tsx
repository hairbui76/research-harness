/**
 * The presentation every research page shares, expressed in the Design System.
 *
 * Nothing here is a new primitive: `Loading`/`Empty` are `AsyncState` and `Skeleton`,
 * `ErrorBox` is `ErrorNotice`, `Panel` is a `Card`, and `StatusBadge` is `AuthorityBadge`
 * when the word the daemon used *is* an authority label and a toned `Badge` otherwise.
 * They exist so that eleven views spell the same thing the same way, not to re-implement
 * anything the package owns (DS spec §12.7).
 *
 * ## How a research page uses these
 *
 * The frame is mounted first and the state goes *inside* it — never in front of it:
 *
 * ```tsx
 * return (
 *   <FullPageWorkspace busy={state.loading} title="Claims" description={…}>
 *     {state.loading ? <Loading what="the claims" shape="table" />
 *      : state.error ? <ErrorBox error={state.error} retry={state.reload} />
 *      : rows.length === 0 ? <Empty description="…" action={…}>No claims yet</Empty>
 *      : <DataTable …>{…}</DataTable>}
 *   </FullPageWorkspace>
 * );
 * ```
 *
 * A page that returns `<Loading/>` instead of itself has no `h1` while it loads, so the
 * shell's skip link lands nowhere and a researcher cannot tell which page they are on. The
 * frame carries the identity; the body carries the state; `busy` marks the content region
 * while the body is a skeleton. A description that quotes a count says the part that is
 * true without the data until the data arrives.
 *
 * These three are the contract the research views share, so they only ever grow: existing
 * props keep their names and their meaning, new ones are optional, and a caller that
 * passes nothing new renders what it rendered before.
 *
 * `StatusBadge` never signals with colour alone: every badge renders the daemon's own word
 * beside its glyph (DS spec §12.6).
 */
import { useState } from 'react';
import type { ReactNode } from 'react';
import {
  AsyncState,
  AuthorityBadge,
  Badge,
  Card,
  ErrorNotice,
  ScrollArea,
  Skeleton,
  AUTHORITY_LABELS,
  humaniseResearchTokens,
  humaniseTerm,
  researchDescription,
  researchLabel,
  useId,
} from '@research-harness/design';
import type {
  AuthorityLabel,
  BadgeProps,
  IconName,
  VocabularyName,
} from '@research-harness/design';
import { useDaemonOutage } from '../app/daemonStatus';

/**
 * What is about to arrive, so the placeholder can be shaped like it: a table of rows, a
 * run of panels, a list of short entries, or a paragraph.
 */
export type LoadingShape = 'text' | 'list' | 'table' | 'cards';

/** The columns a table skeleton draws. Five, because that is the narrowest research table. */
const TABLE_COLUMNS = ['26%', '14%', '16%', '12%', '20%'] as const;

/**
 * Waiting for a read, drawn as the content that is coming rather than as a spinner.
 *
 * The skeleton is hidden from assistive technology and the wait is announced once,
 * politely, in words: a screen reader hears "Reading the claims…" and nothing else, while
 * the page keeps its heading and its shape.
 */
export function Loading({ what, shape = 'text' }: { what: string; shape?: LoadingShape }) {
  return (
    <div className="rh-web-loading">
      <p className="rh-visually-hidden" role="status">{`Reading ${what}…`}</p>
      {shape === 'table' ? (
        <div className="rh-web-skeleton-table">
          {Array.from({ length: 6 }, (_unused, row) => (
            <Skeleton key={row} direction="row" widths={TABLE_COLUMNS} />
          ))}
        </div>
      ) : shape === 'cards' ? (
        <div className="rh-web-stack">
          {Array.from({ length: 3 }, (_unused, card) => (
            <div key={card} className="rh-web-skeleton-card">
              <Skeleton width="40%" />
              <Skeleton lines={3} />
            </div>
          ))}
        </div>
      ) : shape === 'list' ? (
        <div className="rh-web-stack">
          {Array.from({ length: 5 }, (_unused, row) => (
            <Skeleton key={row} lines={2} />
          ))}
        </div>
      ) : (
        <Skeleton lines={3} />
      )}
    </div>
  );
}

/**
 * A read did not produce a page, and why.
 *
 * There are two whys and they read differently. A *refusal* is the daemon answering: it has
 * a sentence of its own, and that sentence is the whole point of the box. Silence is not an
 * answer, and the shell already says so once, at the top of the window, in words that cover
 * every page at once — so restating "could not answer / Failed to fetch" here would be the
 * same fact stated twice and worse, which is exactly the stacked-notice pattern this
 * cockpit is trying to leave behind. During an outage the box says only what is local to
 * this page: that it has nothing to show yet, that nothing was lost, and how to ask again.
 */
export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  const outage = useDaemonOutage();
  const actions = retry
    ? [{ label: 'Try again', onClick: retry, iconStart: 'refresh-cw' as const }]
    : undefined;
  if (outage) {
    // No safety line and no cause: the notice at the top of the window carries both, for
    // every page at once. One sentence, and the way to ask again.
    return (
      <ErrorNotice
        kind="retryable"
        title="Waiting for the daemon"
        description="This page will read itself again as soon as the daemon answers."
        {...(actions ? { actions } : {})}
      />
    );
  }
  return (
    <ErrorNotice
      kind={retry ? 'retryable' : 'fatal'}
      title="The daemon refused or could not answer"
      description={error}
      safety={{ source: 'safe' }}
      {...(actions ? { actions } : {})}
    />
  );
}

/**
 * Nothing to show, and what to do about it.
 *
 * The title is the fact ("No claims yet"); `description` says what this page is for and
 * how the objects on it come to exist; `action` is one real next step — a link to where
 * the object is created, or a button that asks again. An empty state with none of that
 * teaches nothing, which is the state most of these pages were in.
 *
 * `flat` is for an empty that already sits inside a `Panel`, so a card does not end up
 * holding a smaller card.
 */
export function Empty({
  children,
  description,
  action,
  flat,
}: {
  children: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  flat?: boolean;
}) {
  return (
    <AsyncState
      kind="empty"
      // Every title below names the state in the page's own words, so the kind's generic
      // label above it would be a kicker repeating what the sentence already says.
      hideKind
      title={children}
      {...(description === undefined ? {} : { description })}
      {...(flat ? { flat: true } : {})}
    >
      {action === undefined ? null : <div className="rh-web-row">{action}</div>}
    </AsyncState>
  );
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
 *
 * The compact wrapper stays. A corpus or a review queue is read by running the eye down a
 * column, and that is what close rows are for; handing the choice back to nine pages would
 * only mean nine pages making it again. What was wrong was the *text*: the density's font
 * scale used to take a 12px cell to 11.15px, under the size anything readable may be.
 * That is fixed where it was broken — `--rh-type-body-sm-size` is 13px and
 * `.rh-web-table` floors its computed size at `--rh-type-reading-min-size` — so the rows
 * stay dense and the words stay legible, which were never the same decision.
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
  insufficient_evidence: 'circle-help',
  unverified: 'circle-dashed',
  supported: 'circle-check',
  verified: 'circle-check',
  valid: 'circle-check',
  routine: 'list',
};

export interface StatusBadgeProps {
  /** The daemon's own word: the value, not the label. */
  status: string;
  /**
   * Which controlled vocabulary the word belongs to, so the badge can say the product's
   * word for it and — with `describe` — what it means. Without one the identifier is
   * humanised, which is right for a word that stands on its own and wrong for a word a
   * vocabulary explains.
   */
  vocabulary?: VocabularyName;
  size?: 'sm' | 'md';
  /**
   * Put the vocabulary's one-line meaning on the page: the badge takes a tab stop, is
   * `aria-describedby` that sentence, and prints it underneath while it has focus. Turn it
   * on where the status is the subject of the row or the screen; leave it off where the
   * status is incidental, and where the sentence would repeat one already on screen.
   */
  describe?: boolean;
  /** Override the visible wording. The vocabulary still supplies the meaning. */
  children?: ReactNode;
}

/**
 * One word of one of the daemon's vocabularies, drawn as a badge.
 *
 * The scientific authorities go to `AuthorityBadge`, which owns their palette, their glyph
 * and their sentence. Everything else — a queue category, a verifier's verdict, an anchor
 * verdict, a screening state — is application feedback about an object, so it wears a tone
 * and carries its vocabulary's sentence in the same shape the authority badge uses.
 */
export function StatusBadge({
  status,
  vocabulary,
  size = 'sm',
  describe = false,
  children,
}: StatusBadgeProps) {
  const descriptionId = useId(undefined, 'rh-web-status');
  const [shown, setShown] = useState(false);

  const label = children ?? (vocabulary === undefined ? undefined : researchLabel(vocabulary, status));
  if (isAuthority(status)) {
    return (
      <AuthorityBadge
        authority={status}
        size={size}
        describe={describe}
        {...(label === undefined ? {} : { label })}
      />
    );
  }

  const description = vocabulary === undefined ? undefined : researchDescription(vocabulary, status);
  const describing = describe && description !== undefined;
  const icon = ICONS[status];
  const badge = (
    <Badge
      tone={TONES[status] ?? 'neutral'}
      size={size}
      {...(icon ? { icon } : { icon: null })}
      {...(describing
        ? {
            tabIndex: 0,
            'aria-describedby': descriptionId,
            onFocus: () => setShown(true),
            onBlur: () => setShown(false),
          }
        : {})}
    >
      {label ?? humaniseTerm(status)}
    </Badge>
  );
  if (!describing) return badge;

  // The Design System's describable badge, reused rather than restated: these two classes
  // are how the package draws a badge with its meaning under it, and a second shape for
  // the same idea would be a second design.
  return (
    <span className="rh-authority-badge__described">
      {badge}
      <span id={descriptionId} className="rh-visually-hidden">
        {description}
      </span>
      {shown ? (
        <span className="rh-authority-badge__hint" aria-hidden="true">
          {description}
        </span>
      ) : null}
    </span>
  );
}

/**
 * The word for one interrogation field.
 *
 * A project's schema names its own questions, so a field the baseline schema does not
 * declare falls back to the humanised identifier rather than to the identifier itself.
 */
export function fieldLabel(field: string): string {
  return researchLabel('candidateField', field);
}

/**
 * What one staged candidate is called, everywhere it is named: the field's word, then the
 * work the span was read from. The review screen's heading, the queue row, the
 * decide-and-next links, the batch report and the palette all say the same thing.
 */
export function candidateName(field: string, work: string): string {
  return `${fieldLabel(field)} · ${work}`;
}

/**
 * What one attention item is called: the daemon's title, then the id it is held under.
 *
 * A stale object arrives labelled with the node id the dependency graph knows it by —
 * `C0001`, `S0001#W0001#tokenization`, `TX:traffic-shape` — and an id is not a name. The
 * daemon composes the name (`AttentionItem.title`) and this renders it, keeping the id
 * beside it in mono because that is what a researcher repairing the object works with.
 *
 * It lives here rather than in either view because the Overview's "Gone stale" group and
 * the Stale page show the same items: one component is what keeps the two surfaces
 * character-identical, which is the property the browser suite asserts.
 */
export function AttentionName({ item }: { item: { label: string; title?: string } }) {
  if (!item.title) return <code>{item.label}</code>;
  return (
    <>
      {humaniseResearchTokens(item.title)} <code className="rh-web-object-id">{item.label}</code>
    </>
  );
}
