import { forwardRef } from 'react';
import type { HTMLAttributes } from 'react';
import { cx } from '../../utils/cx';
import { Badge } from '../../primitives/Badge';
import { Button } from '../../primitives/Button';
import type { IconName } from '../../primitives/Icon';
import { AsyncState } from '../../states/AsyncState';
import { DescribedTerm } from '../../research/DescribedTerm';
import { AUDIT_SEVERITY_META, describeAuditKind } from '../models';
import type { AuditFindingModel } from '../models';

export interface AuditFindingProps extends Omit<HTMLAttributes<HTMLLIElement>, 'onSelect'> {
  finding: AuditFindingModel;
  /** Opens the source position the finding is about. */
  onOpen?: (file: string, line: number) => void;
  /** Follow the Claim or anchor the finding names. */
  onNavigate?: (target: { kind: 'claim' | 'anchor'; id: string }) => void;
}

/** One thing to do about a finding: what it is called, and what it runs. */
interface FindingAction {
  label: string;
  icon: IconName;
  run: () => void;
}

/**
 * The kinds whose next step is the Claim rather than the source.
 *
 * Wording stronger than the Claim allows, a number the accepted Evidence does not measure,
 * and a Claim the research state moved out from under are all answered by reading the
 * Claim: the sentence is only wrong relative to it. The other three — a sentence attached
 * to no Claim, a citation that does not resolve, an anchor that no longer opens — are
 * answered in the source, which is where the researcher has to type.
 */
const CLAIM_FIRST: ReadonlySet<string> = new Set([
  'over_strong_wording',
  'unsupported_numeric',
  'stale_claim',
]);

/**
 * What to do about this finding, in the order the finding itself decides.
 *
 * A row of chips offering every reference a finding happens to carry is a lint tool's
 * answer to "what now". This picks the one act the kind asks for and offers the other as
 * the quieter second, so the card ends in a next step rather than in a set of links.
 */
function findingActions(
  finding: AuditFindingModel,
  onOpen: AuditFindingProps['onOpen'],
  onNavigate: AuditFindingProps['onNavigate'],
): FindingAction[] {
  const { file, line, claim, anchor } = finding;
  const openSource: FindingAction | undefined =
    onOpen && file !== undefined
      ? { label: 'Open the sentence', icon: 'file-code', run: () => onOpen(file, line ?? 1) }
      : onNavigate && anchor
        ? {
            label: 'Open the anchored sentence',
            icon: 'link',
            run: () => onNavigate({ kind: 'anchor', id: anchor.id }),
          }
        : undefined;
  const openClaim: FindingAction | undefined =
    onNavigate && claim
      ? {
          label: `Open ${claim.label ?? claim.id}`,
          icon: 'bookmark',
          run: () => onNavigate({ kind: 'claim', id: claim.id }),
        }
      : undefined;

  const ordered = CLAIM_FIRST.has(finding.kind)
    ? [openClaim, openSource]
    : [openSource, openClaim];
  return ordered.filter((action): action is FindingAction => action !== undefined);
}

/**
 * One scientific audit finding, as this product states one.
 *
 * The card reads in the order a researcher reads it: the manuscript's own sentence first,
 * quoted; then what the audit found about that sentence, opening with the kind in the
 * sentence's own words; then the one thing to do about it. The kind is never a chip over a
 * heading — a finding is a sentence, and the kind is its first words (DESIGN.md, the Label
 * Is Not a Kicker Rule).
 *
 * A finding is not a compiler diagnostic and never borrows its words: the severity reads
 * "Must fix" / "Review" / "Note" and is drawn in the scientific status family, because a
 * manuscript sentence that accepted state cannot carry is a statement about scientific
 * truth rather than application feedback. A manuscript can compile cleanly and still be
 * full of these.
 */
export const AuditFinding = forwardRef<HTMLLIElement, AuditFindingProps>(function AuditFinding(
  { finding, onOpen, onNavigate, className, ...rest },
  ref,
) {
  const kind = describeAuditKind(finding.kind);
  const severity = AUDIT_SEVERITY_META[finding.severity];
  const position = [finding.file, finding.line === undefined ? undefined : `line ${finding.line}`]
    .filter(Boolean)
    .join(', ');
  const [primary, secondary] = findingActions(finding, onOpen, onNavigate);

  return (
    <li
      ref={ref}
      className={cx('rh-audit-finding', className)}
      data-severity={finding.severity}
      data-kind={finding.kind}
      data-source="audit"
      {...rest}
    >
      {finding.sentence === undefined ? null : (
        <blockquote className="rh-audit-finding__sentence">{finding.sentence}</blockquote>
      )}
      <p className="rh-audit-finding__found">
        <span className="rh-audit-finding__kind">{kind.label}</span>
        {' — '}
        <span className="rh-audit-finding__message">{finding.message}</span>
      </p>
      <div className="rh-audit-finding__foot">
        {/* The severity is a key beside the finding, never a lead-in over it, and it says
            what it means where a researcher has to know Must fix from Review to act. */}
        <DescribedTerm
          className="rh-audit-finding__severity"
          description={severity.description}
        >
          <Badge status={severity.status} size="sm">
            {severity.label}
          </Badge>
        </DescribedTerm>
        {position ? <span className="rh-audit-finding__position">{position}</span> : null}
        {primary ? (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            iconStart={primary.icon}
            onClick={primary.run}
          >
            {primary.label}
          </Button>
        ) : null}
        {secondary ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            iconStart={secondary.icon}
            onClick={secondary.run}
          >
            {secondary.label}
          </Button>
        ) : null}
      </div>
    </li>
  );
});

export interface AuditFindingListProps extends HTMLAttributes<HTMLDivElement> {
  findings: readonly AuditFindingModel[];
  onOpen?: (file: string, line: number) => void;
  onNavigate?: (target: { kind: 'claim' | 'anchor'; id: string }) => void;
  label?: string;
  emptyLabel?: string;
}

/** The scientific audit list. Deliberately a separate list from compiler diagnostics. */
export const AuditFindingList = forwardRef<HTMLDivElement, AuditFindingListProps>(
  function AuditFindingList(
    { findings, onOpen, onNavigate, label = 'Scientific audit', emptyLabel, className, ...rest },
    ref,
  ) {
    if (findings.length === 0) {
      return (
        <div ref={ref} className={cx('rh-audit-finding-list', className)} {...rest}>
          <AsyncState
            kind="empty"
            compact
            title={emptyLabel ?? 'No audit findings'}
            description="Nothing in this manuscript conflicts with accepted state, its citations, or its anchors."
          />
        </div>
      );
    }

    return (
      <div
        ref={ref}
        className={cx('rh-audit-finding-list', className)}
        data-source="audit"
        {...rest}
      >
        <ul className="rh-audit-finding-list__rows" aria-label={label}>
          {findings.map((finding) => (
            <AuditFinding
              key={finding.id}
              finding={finding}
              onOpen={onOpen}
              onNavigate={onNavigate}
            />
          ))}
        </ul>
      </div>
    );
  },
);
