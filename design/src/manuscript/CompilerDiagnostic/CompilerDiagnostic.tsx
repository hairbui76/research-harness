import { forwardRef, useMemo } from 'react';
import type { HTMLAttributes } from 'react';
import { cx } from '../../utils/cx';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { AsyncState } from '../../states/AsyncState';
import { DIAGNOSTIC_SEVERITY_META } from '../models';
import type { DiagnosticModel } from '../models';

export interface CompilerDiagnosticProps extends Omit<HTMLAttributes<HTMLLIElement>, 'onSelect'> {
  diagnostic: DiagnosticModel;
  /** Opens the exact source position. Without it the row is static text. */
  onOpen?: (file: string, line: number) => void;
  /** Hide the file name, because the surrounding group already names it. */
  hideFile?: boolean;
}

function positionText(diagnostic: DiagnosticModel, hideFile: boolean): string {
  const parts: string[] = [];
  if (!hideFile && diagnostic.file) parts.push(diagnostic.file);
  if (diagnostic.line !== undefined) parts.push(`line ${diagnostic.line}`);
  if (diagnostic.column !== undefined) parts.push(`column ${diagnostic.column}`);
  return parts.join(', ');
}

/**
 * One line of compiler output, in the shape the audit beside it uses.
 *
 * What the compiler said is a sentence and the severity is its first word, in the
 * sentence's own type — never an 11px chip over it (DESIGN.md, the Label Is Not a Kicker
 * Rule). The tone is the feedback palette and not a scientific status: a missing brace is
 * an application telling you it failed, not a statement about what is true. Where the
 * finding beside it quotes the manuscript, this quotes the engine: the position it named
 * and the code it raised, under the sentence, beside the one act they lead to.
 */
export const CompilerDiagnostic = forwardRef<HTMLLIElement, CompilerDiagnosticProps>(
  function CompilerDiagnostic({ diagnostic, onOpen, hideFile = false, className, ...rest }, ref) {
    const meta = DIAGNOSTIC_SEVERITY_META[diagnostic.severity];
    const position = positionText(diagnostic, hideFile);
    const openable = onOpen !== undefined && diagnostic.file !== undefined;

    return (
      <li
        ref={ref}
        className={cx('rh-diagnostic', className)}
        data-severity={diagnostic.severity}
        data-source="compiler"
        {...rest}
      >
        <p className="rh-diagnostic__found">
          <Icon name={meta.icon} size={16} />
          <span className="rh-diagnostic__severity">{meta.label}</span>
          {' — '}
          <span className="rh-diagnostic__message">{diagnostic.message}</span>
        </p>
        <div className="rh-diagnostic__foot">
          {position ? <span className="rh-diagnostic__position">{position}</span> : null}
          {diagnostic.code ? <code className="rh-diagnostic__code">{diagnostic.code}</code> : null}
          {openable ? (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              iconStart="file-code"
              onClick={() => onOpen(diagnostic.file as string, diagnostic.line ?? 1)}
            >
              {diagnostic.line === undefined ? 'Open the file' : `Open line ${diagnostic.line}`}
            </Button>
          ) : null}
        </div>
      </li>
    );
  },
);

export interface CompilerDiagnosticListProps extends HTMLAttributes<HTMLDivElement> {
  diagnostics: readonly DiagnosticModel[];
  onOpen?: (file: string, line: number) => void;
  /** Accessible name of the list; the panel supplies a heading instead when it wraps this. */
  label?: string;
  emptyLabel?: string;
}

const NO_FILE = 'Whole document';

/** Compiler diagnostics grouped by the file they were reported against. */
export const CompilerDiagnosticList = forwardRef<HTMLDivElement, CompilerDiagnosticListProps>(
  function CompilerDiagnosticList(
    { diagnostics, onOpen, label = 'Compiler diagnostics', emptyLabel, className, ...rest },
    ref,
  ) {
    const groups = useMemo(() => {
      const byFile = new Map<string, DiagnosticModel[]>();
      for (const diagnostic of diagnostics) {
        const key = diagnostic.file ?? NO_FILE;
        const bucket = byFile.get(key);
        if (bucket) bucket.push(diagnostic);
        else byFile.set(key, [diagnostic]);
      }
      return [...byFile.entries()];
    }, [diagnostics]);

    if (groups.length === 0) {
      return (
        <div ref={ref} className={cx('rh-diagnostic-list', className)} {...rest}>
          <AsyncState
            kind="empty"
            compact
            title={emptyLabel ?? 'No compiler errors or warnings'}
            description="The last build produced no output from the LaTeX engine."
          />
        </div>
      );
    }

    return (
      <div
        ref={ref}
        className={cx('rh-diagnostic-list', className)}
        data-source="compiler"
        {...rest}
      >
        {groups.map(([file, rows]) => (
          // A plain group, not a landmark: the panel around this list is already the
          // region, and nesting regions per file would bury the two headings that matter.
          <div key={file} className="rh-diagnostic-list__group">
            <h4 className="rh-diagnostic-list__file">
              <Icon name="file-code" size={14} />
              <span>{file}</span>
              <span className="rh-diagnostic-list__count">{`${rows.length}`}</span>
            </h4>
            <ul className="rh-diagnostic-list__rows" aria-label={`${label}: ${file}`}>
              {rows.map((diagnostic) => (
                <CompilerDiagnostic
                  key={diagnostic.id}
                  diagnostic={diagnostic}
                  onOpen={onOpen}
                  hideFile
                />
              ))}
            </ul>
          </div>
        ))}
      </div>
    );
  },
);
