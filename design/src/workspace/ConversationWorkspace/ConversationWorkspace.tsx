import { forwardRef } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx } from '../../utils/cx';
import { useControllable } from '../../utils/useControllable';
import { Pane, PaneGroup, PaneHandle } from '../../primitives/ResizablePane';
import { IconButton } from '../../primitives/IconButton';
import { mergePaneSizes, resolvePaneSizes } from '../models';
import type { PaneSizes } from '../models';

/** Pane keys, in visual order. Sizes are stored against these, never against an index. */
const RAIL = 'rail';
const CENTRE = 'centre';
const INSPECTOR = 'inspector';

const DEFAULT_SIZES: PaneSizes = { [RAIL]: 18, [CENTRE]: 54, [INSPECTOR]: 28 };

export interface ConversationWorkspaceProps extends HTMLAttributes<HTMLDivElement> {
  /** The project rail. Omit when an `AppShell` already supplies one. */
  rail?: ReactNode;
  /** The transcript. `Message` and friends live in `design/src/conversation`; wire them here. */
  transcript: ReactNode;
  /** The composer, pinned below the transcript so it never scrolls away. */
  composer: ReactNode;
  /** The research inspector. */
  inspector?: ReactNode;
  inspectorOpen?: boolean;
  defaultInspectorOpen?: boolean;
  onInspectorOpenChange?: (open: boolean) => void;
  /** Pane sizes as percentages, keyed by pane, so collapsing the inspector keeps them. */
  paneSizes?: PaneSizes;
  defaultPaneSizes?: PaneSizes;
  onPaneSizesChange?: (sizes: PaneSizes) => void;
  railLabel?: string;
  transcriptLabel?: string;
  inspectorLabel?: string;
  /** Toolbar content above the transcript, beside the inspector toggle. */
  toolbar?: ReactNode;
}

/**
 * The conversation-first three-pane workspace: rail, transcript with its composer, and
 * the research inspector.
 *
 * Every pane is a slot — the transcript, the composer and the inspector are supplied by
 * the application, which is what keeps `design/src/conversation` and this file
 * independent of each other. Collapsing the inspector leaves the toggle exactly where it
 * was, in the centre pane's toolbar, so focus does not move when the pane it controls
 * disappears.
 */
export const ConversationWorkspace = forwardRef<HTMLDivElement, ConversationWorkspaceProps>(
  function ConversationWorkspace(
    {
      rail,
      transcript,
      composer,
      inspector,
      inspectorOpen,
      defaultInspectorOpen = true,
      onInspectorOpenChange,
      paneSizes,
      defaultPaneSizes,
      onPaneSizesChange,
      railLabel = 'Sessions',
      transcriptLabel = 'Conversation',
      inspectorLabel = 'Research inspector',
      toolbar,
      className,
      ...rest
    },
    ref,
  ) {
    const [open, setOpen] = useControllable<boolean>({
      value: inspectorOpen,
      defaultValue: defaultInspectorOpen,
      onChange: onInspectorOpenChange,
    });
    const [sizes, setSizes] = useControllable<PaneSizes>({
      value: paneSizes,
      defaultValue: defaultPaneSizes ?? DEFAULT_SIZES,
      onChange: onPaneSizesChange,
    });

    const keys = [
      ...(rail === undefined ? [] : [RAIL]),
      CENTRE,
      ...(inspector !== undefined && open ? [INSPECTOR] : []),
    ];
    const resolved = resolvePaneSizes(sizes, keys, DEFAULT_SIZES);

    return (
      <div ref={ref} className={cx('rh-conversation-workspace', className)} {...rest}>
        <PaneGroup
          direction="horizontal"
          sizes={resolved}
          onLayoutChange={(next) => setSizes(mergePaneSizes(sizes, keys, next))}
        >
          {rail === undefined ? null : (
            <Pane className="rh-conversation-workspace__rail" minSize={12} maxSize={35}>
              {rail}
            </Pane>
          )}
          {rail === undefined ? null : <PaneHandle label={`Resize the ${railLabel.toLowerCase()} pane`} />}

          <Pane className="rh-conversation-workspace__centre" minSize={30}>
            <div className="rh-conversation-workspace__toolbar">
              <div className="rh-conversation-workspace__toolbar-slot">{toolbar}</div>
              {inspector === undefined ? null : (
                <IconButton
                  className="rh-conversation-workspace__inspector-toggle"
                  icon={open ? 'panel-right' : 'panel-left'}
                  size="sm"
                  label={
                    open
                      ? `Collapse the ${inspectorLabel.toLowerCase()}`
                      : `Expand the ${inspectorLabel.toLowerCase()}`
                  }
                  aria-expanded={open}
                  onClick={() => setOpen(!open)}
                />
              )}
            </div>
            <div
              className="rh-conversation-workspace__transcript"
              role="group"
              aria-label={transcriptLabel}
            >
              {transcript}
            </div>
            <div className="rh-conversation-workspace__composer">{composer}</div>
          </Pane>

          {inspector !== undefined && open ? (
            <PaneHandle label={`Resize the ${inspectorLabel.toLowerCase()}`} />
          ) : null}
          {inspector !== undefined && open ? (
            <Pane className="rh-conversation-workspace__inspector" minSize={18} maxSize={45}>
              {inspector}
            </Pane>
          ) : null}
        </PaneGroup>
      </div>
    );
  },
);
