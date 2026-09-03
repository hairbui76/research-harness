import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useId } from '../../hooks/useId';
import { Icon } from '../../primitives/Icon';
import { AuditFindingList } from '../AuditFinding';
import { CompilerDiagnosticList } from '../CompilerDiagnostic';
import type { AuditFindingModel, DiagnosticModel } from '../models';

export interface DiagnosticsPanelProps extends HTMLAttributes<HTMLDivElement> {
  diagnostics: readonly DiagnosticModel[];
  findings: readonly AuditFindingModel[];
  onOpenSource?: (file: string, line: number) => void;
  onNavigate?: (target: { kind: 'claim' | 'anchor'; id: string }) => void;
  /** Rendered above both lists — `CompilerStatus`, in the manuscript workspace. */
  status?: ReactNode;
  compilerHeading?: string;
  auditHeading?: string;
}

function countWord(count: number, singular: string): string {
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

/**
 * The two lists a manuscript produces, under two headings that never merge.
 *
 * A document may compile while failing scientific audit, or pass audit while failing to
 * compile (LaTeX workspace spec §7). Keeping the headings, the wording and the counts
 * separate is what stops a reader treating a clean compile as a clean paper.
 */
export const DiagnosticsPanel = forwardRef<HTMLDivElement, DiagnosticsPanelProps>(
  function DiagnosticsPanel(
    {
      diagnostics,
      findings,
      onOpenSource,
      onNavigate,
      status,
      compilerHeading = 'Compiler diagnostics',
      auditHeading = 'Scientific audit',
      className,
      id,
      ...rest
    },
    ref,
  ) {
    const baseId = useId(id, 'rh-diagnostics');
    const compilerId = `${baseId}-compiler`;
    const auditId = `${baseId}-audit`;

    return (
      <div ref={ref} id={baseId} className={cx('rh-diagnostics-panel', className)} {...rest}>
        {status}

        <section className="rh-diagnostics-panel__section" aria-labelledby={compilerId}>
          <h3 className="rh-diagnostics-panel__heading" id={compilerId}>
            <Icon name="wrench" size={16} />
            <span>{compilerHeading}</span>
            <span className="rh-diagnostics-panel__count">
              {countWord(diagnostics.length, 'message')}
            </span>
          </h3>
          <p className="rh-diagnostics-panel__note">
            What the LaTeX engine reported about this build.
          </p>
          <CompilerDiagnosticList
            diagnostics={diagnostics}
            onOpen={onOpenSource}
            label={compilerHeading}
          />
        </section>

        <section className="rh-diagnostics-panel__section" aria-labelledby={auditId}>
          <h3 className="rh-diagnostics-panel__heading" id={auditId}>
            <Icon name="microscope" size={16} />
            <span>{auditHeading}</span>
            <span className="rh-diagnostics-panel__count">
              {countWord(findings.length, 'finding')}
            </span>
          </h3>
          <p className="rh-diagnostics-panel__note">
            What the manuscript claims, checked against accepted state. Separate from the
            compiler: a document can compile and still fail this.
          </p>
          <AuditFindingList
            findings={findings}
            onOpen={onOpenSource}
            onNavigate={onNavigate}
            label={auditHeading}
          />
        </section>
      </div>
    );
  },
);
