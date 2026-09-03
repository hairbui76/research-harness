import { forwardRef } from 'react';
import type { HTMLAttributes, ReactElement } from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { useId } from '../../hooks/useId';
import { Badge } from '../../primitives/Badge';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { Tooltip } from '../../primitives/Tooltip';
import type { CandidateDiffModel, DiffHunk, DiffLine, SemanticSummary } from '../models';

export type DiffView = 'unified' | 'side-by-side';

export interface CandidateDiffProps extends Omit<HTMLAttributes<HTMLElement>, 'onSelect'> {
  diff: CandidateDiffModel;
  view?: DiffView;
  defaultView?: DiffView;
  onViewChange?: (view: DiffView) => void;
  /** Always an explicit click. Nothing in this component applies a candidate on its own. */
  onApply?: () => void;
  onReject?: () => void;
  /** Opens the assistant message this candidate came back from. */
  onOpenOrigin?: (messageId: string) => void;
  applying?: boolean;
}

const AUDIT_META: Record<
  CandidateDiffModel['auditStatus'],
  { label: string; tone: 'info' | 'success' | 'error'; icon: 'circle-dashed' | 'circle-check' | 'alert-circle' }
> = {
  pending: { label: 'Audit pending', tone: 'info', icon: 'circle-dashed' },
  passed: { label: 'Audit passed', tone: 'success', icon: 'circle-check' },
  failed: { label: 'Audit failed', tone: 'error', icon: 'alert-circle' },
};

const SUMMARY_SECTIONS: Array<{ key: keyof SemanticSummary; label: string }> = [
  { key: 'added', label: 'Added propositions' },
  { key: 'removed', label: 'Removed propositions' },
  { key: 'weakened', label: 'Weakened propositions' },
  { key: 'strengthened', label: 'Strengthened propositions' },
];

const LINE_PREFIX: Record<DiffLine['kind'], string> = {
  context: ' ',
  added: '+',
  removed: '-',
};

const LINE_WORD: Record<DiffLine['kind'], string> = {
  context: 'unchanged',
  added: 'added',
  removed: 'removed',
};

function ProtectedMarker({ span }: { span: { kind: string; reason: string } }): ReactElement {
  return (
    <Tooltip content={span.reason}>
      <span className="rh-candidate-diff__protected" tabIndex={0}>
        <Icon name="shield" size={14} />
        {`protected: ${span.kind}`}
      </span>
    </Tooltip>
  );
}

function DiffLineRow({ line }: { line: DiffLine }): ReactElement {
  return (
    <div className="rh-candidate-diff__line" data-kind={line.kind}>
      <span className="rh-candidate-diff__sigil" aria-hidden="true">
        {LINE_PREFIX[line.kind]}
      </span>
      <span className="rh-visually-hidden">{LINE_WORD[line.kind]}</span>
      <code className="rh-candidate-diff__text">{line.text}</code>
      {line.protected ? <ProtectedMarker span={line.protected} /> : null}
    </div>
  );
}

/** Pairs removed/added lines into rows so the two columns stay aligned. */
function sideBySideRows(hunk: DiffHunk): Array<{ left?: DiffLine; right?: DiffLine }> {
  const rows: Array<{ left?: DiffLine; right?: DiffLine }> = [];
  let index = 0;
  while (index < hunk.lines.length) {
    const line = hunk.lines[index];
    if (!line) break;
    if (line.kind === 'context') {
      rows.push({ left: line, right: line });
      index += 1;
      continue;
    }
    const removed: DiffLine[] = [];
    const added: DiffLine[] = [];
    while (index < hunk.lines.length && hunk.lines[index]?.kind === 'removed') {
      removed.push(hunk.lines[index] as DiffLine);
      index += 1;
    }
    while (index < hunk.lines.length && hunk.lines[index]?.kind === 'added') {
      added.push(hunk.lines[index] as DiffLine);
      index += 1;
    }
    const height = Math.max(removed.length, added.length);
    for (let offset = 0; offset < height; offset += 1) {
      const left = removed[offset];
      const right = added[offset];
      rows.push({
        ...(left ? { left } : {}),
        ...(right ? { right } : {}),
      });
    }
  }
  return rows;
}

function SideBySide({ hunk }: { hunk: DiffHunk }): ReactElement {
  const rows = sideBySideRows(hunk);
  return (
    <div className="rh-candidate-diff__columns">
      <div className="rh-candidate-diff__column" data-side="before">
        <h5>Before</h5>
        {rows.map((row, rowIndex) =>
          row.left ? (
            <DiffLineRow key={`before-${rowIndex}`} line={row.left} />
          ) : (
            <div
              key={`before-${rowIndex}`}
              className="rh-candidate-diff__line"
              data-kind="blank"
            />
          ),
        )}
      </div>
      <div className="rh-candidate-diff__column" data-side="after">
        <h5>After</h5>
        {rows.map((row, rowIndex) =>
          row.right ? (
            <DiffLineRow key={`after-${rowIndex}`} line={row.right} />
          ) : (
            <div key={`after-${rowIndex}`} className="rh-candidate-diff__line" data-kind="blank" />
          ),
        )}
      </div>
    </div>
  );
}

/**
 * A staged edit to the manuscript, presented for review.
 *
 * The component never applies anything: Apply is a click, and it is disabled with the
 * host's stated reason whenever the audit failed or a protected span moved. Protected
 * lines — citations, equations, numbers, units, anchors, qualifiers — carry a written
 * marker as well as a tint, and the semantic summary says what the candidate does to the
 * propositions in the source rather than only which characters changed.
 */
export const CandidateDiff = forwardRef<HTMLElement, CandidateDiffProps>(function CandidateDiff(
  {
    diff,
    view,
    defaultView = 'unified',
    onViewChange,
    onApply,
    onReject,
    onOpenOrigin,
    applying = false,
    className,
    id,
    ...rest
  },
  ref,
) {
  const baseId = useId(id, 'rh-candidatediff');
  const blockedId = `${baseId}-blocked`;
  const [currentView, setView] = useControllable<DiffView>({
    value: view,
    defaultValue: defaultView,
    onChange: onViewChange,
  });

  const audit = AUDIT_META[diff.auditStatus];
  const blockedReason =
    diff.blockedReason ??
    (diff.auditStatus === 'failed'
      ? 'The scientific audit failed for this candidate. Fix the finding or reject the edit.'
      : undefined);
  const applyBlocked = blockedReason !== undefined;
  const summarySections = SUMMARY_SECTIONS.filter(
    (section) => diff.semanticSummary[section.key].length > 0,
  );

  return (
    <article
      ref={ref}
      id={baseId}
      aria-label={`Candidate edit to ${diff.file}`}
      className={cx('rh-candidate-diff', className)}
      data-audit={diff.auditStatus}
      data-view={currentView}
      {...rest}
    >
      <header className="rh-candidate-diff__header">
        <h3 className="rh-candidate-diff__file">
          <Icon name="git-compare" size={16} />
          <span>{diff.file}</span>
        </h3>
        <Badge status="candidate" size="sm" />
        <Badge tone={audit.tone} icon={audit.icon} size="sm">
          {audit.label}
        </Badge>

        <div className="rh-candidate-diff__views" role="group" aria-label="Diff layout">
          <button
            type="button"
            className="rh-candidate-diff__view"
            aria-pressed={currentView === 'unified'}
            onClick={() => setView('unified')}
          >
            <Icon name="rows-2" size={14} />
            Unified
          </button>
          <button
            type="button"
            className="rh-candidate-diff__view"
            aria-pressed={currentView === 'side-by-side'}
            onClick={() => setView('side-by-side')}
          >
            <Icon name="columns-2" size={14} />
            Side by side
          </button>
        </div>
      </header>

      {diff.originMessageId || diff.contextPackId ? (
        <p className="rh-candidate-diff__origin">
          {diff.originMessageId ? (
            <button
              type="button"
              className="rh-candidate-diff__origin-link"
              disabled={!onOpenOrigin}
              onClick={() => onOpenOrigin?.(diff.originMessageId as string)}
            >
              <Icon name="message-square" size={14} />
              {`Open message ${diff.originMessageId}`}
            </button>
          ) : null}
          {diff.contextPackId ? (
            <span className="rh-candidate-diff__pack">{`Context used: ${diff.contextPackId}`}</span>
          ) : null}
        </p>
      ) : null}

      <section className="rh-candidate-diff__summary" aria-label="What this candidate changes">
        {summarySections.length === 0 ? (
          <p className="rh-candidate-diff__summary-empty">
            No propositional change: wording only.
          </p>
        ) : (
          summarySections.map((section) => (
            <div key={section.key} className="rh-candidate-diff__summary-group" data-group={section.key}>
              <h4>
                {section.label}
                <span className="rh-candidate-diff__summary-count">
                  {diff.semanticSummary[section.key].length}
                </span>
              </h4>
              <ul>
                {diff.semanticSummary[section.key].map((entry) => (
                  <li key={entry}>{entry}</li>
                ))}
              </ul>
            </div>
          ))
        )}
      </section>

      <div className="rh-candidate-diff__hunks">
        {diff.hunks.map((hunk, hunkIndex) => (
          <section
            key={hunk.header ?? `hunk-${hunkIndex}`}
            className="rh-candidate-diff__hunk"
            aria-label={hunk.header ?? `Change ${hunkIndex + 1}`}
          >
            {hunk.header ? <p className="rh-candidate-diff__hunk-header">{hunk.header}</p> : null}
            {currentView === 'unified' ? (
              <div className="rh-candidate-diff__lines">
                {hunk.lines.map((line, lineIndex) => (
                  <DiffLineRow key={`${lineIndex}-${line.text}`} line={line} />
                ))}
              </div>
            ) : (
              <SideBySide hunk={hunk} />
            )}
          </section>
        ))}
      </div>

      <footer className="rh-candidate-diff__footer">
        <Button
          variant="primary"
          size="sm"
          iconStart="check"
          loading={applying}
          disabled={!onApply || applyBlocked}
          aria-describedby={applyBlocked ? blockedId : undefined}
          onClick={onApply}
        >
          Apply to source
        </Button>
        <Button
          variant="secondary"
          size="sm"
          iconStart="x"
          disabled={!onReject}
          onClick={onReject}
        >
          Reject
        </Button>
        {applyBlocked ? (
          <p id={blockedId} className="rh-candidate-diff__blocked" data-tone="blocked">
            <Icon name="shield-off" size={14} />
            <span>{blockedReason}</span>
          </p>
        ) : (
          <p className="rh-candidate-diff__blocked" data-tone="neutral">
            <Icon name="info" size={14} />
            <span>Applying writes the file. Nothing is written until you click Apply.</span>
          </p>
        )}
      </footer>
    </article>
  );
});
