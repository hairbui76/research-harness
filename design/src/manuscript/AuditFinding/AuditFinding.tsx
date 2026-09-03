import { forwardRef } from 'react';
import type { HTMLAttributes } from 'react';
import { cx } from '../../utils/cx';
import { Icon } from '../../primitives/Icon';
import { AsyncState } from '../../states/AsyncState';
import { AUDIT_SEVERITY_META, describeAuditKind } from '../models';
import type { AuditFindingModel } from '../models';

export interface AuditFindingProps extends Omit<HTMLAttributes<HTMLLIElement>, 'onSelect'> {
  finding: AuditFindingModel;
  /** Opens the source position the finding is about. */
  onOpen?: (file: string, line: number) => void;
  /** Follow the Claim or anchor the finding names. */
  onNavigate?: (target: { kind: 'claim' | 'anchor'; id: string }) => void;
}

/**
 * One scientific audit finding.
 *
 * A finding is not a compiler diagnostic and never borrows its words: the kind ("Citation
 * mismatch", "Stale claim") leads the row, the severity reads "Must fix" / "Review" /
 * "Note", and the icons come from a separate family. A manuscript can compile cleanly and
 * still be full of these.
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
  const openable = onOpen !== undefined && finding.file !== undefined;

  const body = (
    <>
      <Icon name={kind.icon} size={16} />
      <span className="rh-audit-finding__kind">{kind.label}</span>
      <span className="rh-audit-finding__message">{finding.message}</span>
      {position ? <span className="rh-audit-finding__position">{position}</span> : null}
    </>
  );

  return (
    <li
      ref={ref}
      className={cx('rh-audit-finding', className)}
      data-severity={finding.severity}
      data-kind={finding.kind}
      data-source="audit"
      {...rest}
    >
      <span className="rh-audit-finding__severity">{severity.label}</span>
      {openable ? (
        <button
          type="button"
          className="rh-audit-finding__button"
          onClick={() => onOpen(finding.file as string, finding.line ?? 1)}
        >
          {body}
        </button>
      ) : (
        <span className="rh-audit-finding__button">{body}</span>
      )}
      {finding.claim !== undefined || finding.anchor !== undefined ? (
        <span className="rh-audit-finding__refs">
          {finding.claim ? (
            <button
              type="button"
              className="rh-audit-finding__ref"
              disabled={!onNavigate}
              onClick={() => onNavigate?.({ kind: 'claim', id: finding.claim?.id ?? '' })}
            >
              <Icon name="bookmark" size={14} />
              {finding.claim.label ?? finding.claim.id}
            </button>
          ) : null}
          {finding.anchor ? (
            <button
              type="button"
              className="rh-audit-finding__ref"
              disabled={!onNavigate}
              onClick={() => onNavigate?.({ kind: 'anchor', id: finding.anchor?.id ?? '' })}
            >
              <Icon name="link" size={14} />
              {finding.anchor.id}
            </button>
          ) : null}
        </span>
      ) : null}
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
