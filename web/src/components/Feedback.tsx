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
import type { ReactNode } from 'react';
import {
  AsyncState,
  AuthorityBadge,
  Badge,
  Card,
  DescribedTerm,
  ErrorNotice,
  ScrollArea,
  Skeleton,
  AUTHORITY_LABELS,
  humaniseResearchTokens,
  humaniseTerm,
  researchDescription,
  researchLabel,
  researchMeaning,
  useDescribedTerm,
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
 * every page at once — the cause, the command, what is safe, and one way to ask again. A
 * second notice here was the same condition stated twice with a second retry button under
 * the first, which is exactly the stacked-notice pattern this cockpit is trying to leave
 * behind. So during an outage a page that has nothing left to show says one quiet line — no
 * box, no tone, no button — and a page that still has its last answer keeps it
 * (`useAsync`) and says nothing here at all.
 */
export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  const outage = useDaemonOutage();
  const actions = retry
    ? [{ label: 'Try again', onClick: retry, iconStart: 'refresh-cw' as const }]
    : undefined;
  if (outage) {
    return (
      <p className="rh-text-secondary" role="status">
        {outage.lastReadAt === null
          ? 'Nothing has been read here yet. This page reads itself as soon as the daemon answers.'
          : `Last read at ${clockTime(outage.lastReadAt)}. This page reads itself again as soon as the daemon answers.`}
      </p>
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
 * A time of day, in the reader's own locale, for a sentence about how old something is.
 *
 * The clock and not the date: an outage lasts minutes and a researcher reads "14:32", not
 * an ISO instant. A time this window cannot parse is printed as it came rather than as
 * "Invalid Date".
 */
export function clockTime(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
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
  description,
  action,
  children,
}: {
  title: ReactNode;
  /**
   * One sentence about the whole panel, above its contents.
   *
   * It belongs to the group rather than to any row in it, which is the point: a fact that
   * is true of every row is stated once here instead of under each of them. It sits in the
   * body rather than the header because the header is a row — the title and its action —
   * and a sentence in it would sit beside the title rather than under it.
   */
  description?: ReactNode;
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
      <div className="rh-web-stack rh-web-stack--tight">
        {description === undefined ? null : (
          <p className="rh-text-secondary">{description}</p>
        )}
        {children}
      </div>
    </Card>
  );
}

export interface FieldProps {
  /** The label the daemon uses for this key. */
  label: string;
  /**
   * Which controlled vocabulary the value belongs to, so the row can print the product's
   * word for it and — with `describe` — what it means.
   */
  vocabulary?: VocabularyName;
  /** The daemon's own value, when this row carries one word of that vocabulary. */
  value?: string;
  /**
   * Put the vocabulary's meaning on the page: the value takes a tab stop, is
   * `aria-describedby` its sentence, and prints it underneath while it has focus — the
   * same act `StatusBadge` performs for a state that is a badge. A value the product says
   * nothing about stays plain text rather than offering a tab stop that leads nowhere.
   */
  describe?: boolean;
  /** What the row shows, when it is not one word of a vocabulary. */
  children?: ReactNode;
}

/**
 * A definition row: the label the daemon uses, and the value it reported.
 *
 * Most of what a review screen prints is a `<dd>` rather than a badge — an absence state,
 * a strength, an origin — and those were the words a first-timer met with nothing on the
 * page to define them (critique 2026-09-07, heuristic 10). Naming the row's vocabulary is
 * what lets it spell the value in the product's word; adding `describe` is what puts the
 * meaning one press away.
 */
export function Field({ label, vocabulary, value, describe = false, children }: FieldProps) {
  const word =
    children ?? (vocabulary !== undefined && value !== undefined
      ? researchLabel(vocabulary, value)
      : null);
  const meaning =
    describe && vocabulary !== undefined && value !== undefined
      ? researchMeaning(vocabulary, value)
      : undefined;
  return (
    <div className="rh-web-field">
      <dt className="rh-text-label">{label}</dt>
      <dd>
        {meaning === undefined ? word : <DescribedTerm description={meaning}>{word}</DescribedTerm>}
      </dd>
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
 *
 * ## Green is the accepted state's, and nothing else's
 *
 * The feedback tones are not separate hues: `success` resolves to the same green as the
 * accepted status family, `error` to the same red as contested, `info` to the same blue as
 * candidate (`themes/dark.css`). So "a feedback tone on a scientific state" and "a
 * scientific family colour on something that is not one" are, in a badge, the same defect
 * — and DESIGN.md forbids both.
 *
 * Four words used to commit it by wearing `success`, and the corpus showed the cost:
 * `Included` sat in the accepted green one column from a count of accepted evidence, so
 * membership of the corpus and acceptance by a researcher read as the same thing. They are
 * not the same thing, and the difference is the product's whole claim: only a persisted
 * human decision creates authority. A verified extraction is not accepted; a supported
 * claim is not accepted; an anchor that still replays is not accepted; a screened work is
 * not accepted. None of them is green any more. Each keeps its own glyph, which is what
 * told them apart in greyscale all along, and green now appears on exactly one badge in
 * the cockpit: the one that says `Accepted`.
 *
 * `unverified` was the other crossing and the louder one. It is what the queue shows when
 * *nothing has verified a candidate yet* — the resting state of every candidate ever
 * staged — and it wore amber, the one hue the system reserves for application feedback,
 * beside the scientific blue of `Candidate` on the same row. An absent verdict is not a
 * warning. It is neutral, with the dashed circle that says "not settled".
 *
 * `unsupported` stays `error`. It is a claim's scientific state, so by the letter of the
 * rule it should not wear a feedback tone at all — but the tone is the contested red, and
 * `authorityOf` already paints an unsupported claim's marker in the contested family two
 * columns away. Moving the badge into that family would be the product classifying an
 * unsupported claim as contested, which is a scientific statement and belongs to the
 * researcher, not to a stylesheet.
 */
export const TONES: Record<string, BadgeProps['tone']> = {
  // A conflict, a broken anchor and a contradicted candidate are conditions the
  // application is reporting about its own work, which is what a feedback tone is for.
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
  routine: 'neutral',
  info: 'info',
};

/**
 * The glyph beside each word.
 *
 * It is the channel that survives greyscale, and for the words that carry no tone it is
 * now the only channel there is: four neutral screening badges are told apart here and
 * nowhere else.
 */
const ICONS: Record<string, IconName> = {
  // Screening (Product 14): where a work stands between a discovery result and the corpus.
  // A discovery result, a screened candidate, a member and a rejection — four steps of one
  // pipeline, none of which is accepted state, all of them neutral and told apart by these.
  discovered: 'search',
  screened: 'filter',
  included: 'library',
  excluded: 'circle-x',
  conflict: 'alert-triangle',
  unsupported: 'circle-x',
  error: 'alert-circle',
  missing: 'link-2-off',
  high_risk: 'alert-triangle',
  ambiguous: 'circle-help',
  relocated: 'arrow-right',
  partially_supported: 'info',
  insufficient_evidence: 'circle-help',
  // Nothing has verified this yet: a dashed circle, because the verdict is not settled
  // rather than bad.
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
   * `aria-describedby` that sentence, and prints it underneath when a reader asks — with
   * focus, with a pointer that rests on it, or with a long press. Turn it on where the
   * status is the subject of the row or the screen; leave it off where the status is
   * incidental, and where the sentence would repeat one already on screen.
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
  const description = vocabulary === undefined ? undefined : researchDescription(vocabulary, status);
  // The package's own hook, so the three gestures that open a meaning — focus, a pointer
  // that rests, a long press — are decided in one place for every word in the cockpit. It
  // is called unconditionally, above the authority branch, because it is a hook.
  const term = useDescribedTerm(describe ? description : undefined);

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

  const icon = ICONS[status];
  const badge = (
    <Badge
      tone={TONES[status] ?? 'neutral'}
      size={size}
      {...(icon ? { icon } : { icon: null })}
      {...term.word}
    >
      {label ?? humaniseTerm(status)}
    </Badge>
  );
  if (term.named === null) return badge;

  // The Design System's describable badge, reused rather than restated: these two classes
  // are how the package draws a badge with its meaning under it, and a second shape for
  // the same idea would be a second design. Where a row cannot grow — a queue row, a table
  // cell — the cockpit's stylesheet hands the sentence a line of its own beneath the row
  // by these same names, so the row's own links never move.
  return (
    <span className="rh-authority-badge__described">
      {badge}
      {term.named}
      {term.shown ? (
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
