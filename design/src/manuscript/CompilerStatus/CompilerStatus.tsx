import { forwardRef } from 'react';
import type { HTMLAttributes } from 'react';
import { cx } from '../../utils/cx';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { Progress } from '../../primitives/Progress';
import { BUILD_STATUS_META, formatDuration, formatTimestamp } from '../models';
import type { BuildModel } from '../models';

export interface CompilerStatusProps extends HTMLAttributes<HTMLDivElement> {
  build: BuildModel;
  /** Terminate a running compile. The component never stops anything itself. */
  onStop?: () => void;
  onCompile?: () => void;
  /** Determinate progress, 0-100. Omit for the indeterminate bar. */
  progress?: number;
}

/**
 * What the compiler did, in the compiler's own terms: which engine ran, when it started
 * and finished, whether the result is usable, and whether source/PDF navigation is
 * available. Scientific audit is a separate list with separate words — see `AuditFinding`.
 */
export const CompilerStatus = forwardRef<HTMLDivElement, CompilerStatusProps>(
  function CompilerStatus({ build, onStop, onCompile, progress, className, ...rest }, ref) {
    const meta = BUILD_STATUS_META[build.status];
    const running = build.status === 'running';
    const duration = formatDuration(build.startedAt, build.finishedAt);

    return (
      <div
        ref={ref}
        className={cx('rh-compiler-status', className)}
        data-status={build.status}
        data-tone={meta.tone}
        {...rest}
      >
        <div className="rh-compiler-status__head">
          <p className="rh-compiler-status__state" role="status">
            <Icon name={meta.icon} size={16} />
            <span>{meta.label}</span>
          </p>
          {running && onStop ? (
            <Button size="sm" variant="danger" iconStart="square" onClick={onStop}>
              Stop
            </Button>
          ) : null}
          {!running && onCompile ? (
            <Button size="sm" variant="primary" iconStart="play" onClick={onCompile}>
              Compile
            </Button>
          ) : null}
        </div>

        {running ? (
          <Progress
            className="rh-compiler-status__progress"
            label="Compiling the manuscript"
            value={progress ?? 0}
            indeterminate={progress === undefined}
            showValue
            size="sm"
          />
        ) : null}

        <dl className="rh-compiler-status__facts">
          <div>
            <dt>Engine</dt>
            <dd>{build.engine ?? 'not selected'}</dd>
          </div>
          <div>
            <dt>Build</dt>
            <dd>{build.buildId ?? 'none yet'}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{formatTimestamp(build.startedAt)}</dd>
          </div>
          <div>
            <dt>Finished</dt>
            <dd>{build.finishedAt ? formatTimestamp(build.finishedAt) : 'still running'}</dd>
          </div>
          {duration ? (
            <div>
              <dt>Took</dt>
              <dd>{duration}</dd>
            </div>
          ) : null}
        </dl>

        <p className="rh-compiler-status__synctex">
          <Icon name={build.synctex === 'available' ? 'crosshair' : 'link-2-off'} size={14} />
          <span>
            {build.synctex === 'available'
              ? 'Source and PDF navigation is available for this build.'
              : `Source and PDF navigation is unavailable${
                  build.synctexReason ? `: ${build.synctexReason}` : '.'
                }`}
          </span>
        </p>

        {build.setupGuidance ? (
          <p className="rh-compiler-status__guidance">
            <Icon name="wrench" size={14} />
            <span>{build.setupGuidance}</span>
          </p>
        ) : null}

        {build.lastGood ? (
          <p className="rh-compiler-status__last-good">
            <Icon name="history" size={14} />
            <span>{`Last successful PDF: ${formatTimestamp(build.lastGood.producedAt)}`}</span>
          </p>
        ) : null}
      </div>
    );
  },
);
