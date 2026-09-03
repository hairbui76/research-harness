import { forwardRef, useMemo } from 'react';
import type { HTMLAttributes } from 'react';
import { cx } from '../../utils/cx';
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

/** One line of compiler output: severity word, message, position, and the compiler's code. */
export const CompilerDiagnostic = forwardRef<HTMLLIElement, CompilerDiagnosticProps>(
  function CompilerDiagnostic({ diagnostic, onOpen, hideFile = false, className, ...rest }, ref) {
    const meta = DIAGNOSTIC_SEVERITY_META[diagnostic.severity];
    const position = positionText(diagnostic, hideFile);
    const openable = onOpen !== undefined && diagnostic.file !== undefined;

    const body = (
      <>
        <Icon name={meta.icon} size={16} />
        <span className="rh-diagnostic__severity">{meta.label}</span>
        <span className="rh-diagnostic__message">{diagnostic.message}</span>
        {position ? <span className="rh-diagnostic__position">{position}</span> : null}
        {diagnostic.code ? <code className="rh-diagnostic__code">{diagnostic.code}</code> : null}
      </>
    );

    return (
      <li
        ref={ref}
        className={cx('rh-diagnostic', className)}
        data-severity={diagnostic.severity}
        data-source="compiler"
        {...rest}
      >
        {openable ? (
          <button
            type="button"
            className="rh-diagnostic__button"
            onClick={() => onOpen(diagnostic.file as string, diagnostic.line ?? 1)}
          >
            {body}
          </button>
        ) : (
          <span className="rh-diagnostic__button" aria-disabled="true">
            {body}
          </span>
        )}
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
