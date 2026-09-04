import { forwardRef } from 'react';
import type { ReactNode } from 'react';
import { AsyncState } from './AsyncState';
import type { AsyncStateProps } from './AsyncState';
import type { AsyncStateKind, SafetyNote, StateAction } from './types';
import type { IconName } from '../primitives/Icon';

/**
 * The named states the Research Harness actually produces, as a discriminated union.
 *
 * Naming them here keeps the wording, the kind and the safety statement identical wherever
 * they appear - the composer, the inspector, the graph pane and the manuscript workspace
 * all describe "provider unavailable" the same way.
 */
export type ResearchStateCase =
  /** No network: the workspace still works, model calls do not. */
  | { case: 'offline' }
  /** The selected provider did not answer. */
  | { case: 'provider-unavailable'; provider?: string }
  /** The model cannot accept this attachment type at all. */
  | { case: 'attachment-unsupported'; filename?: string; reason?: string }
  /** The attachment exists but was left out of the context pack. */
  | { case: 'attachment-omitted'; filename?: string; reason?: string }
  /** A privacy or egress rule refused to let the content leave the workspace. */
  | { case: 'egress-blocked'; policy?: string }
  /** The disposable graph/search index is being rebuilt right now. */
  | { case: 'index-rebuilding'; progress?: number }
  /** No index has been built yet, so the narrower canonical reads are answering. */
  | { case: 'index-absent' }
  /** An index exists but cannot be read, so the narrower canonical reads are answering. */
  | { case: 'index-unreadable' }
  /** The document moved under a recorded source anchor. */
  | { case: 'anchor-stale'; anchor?: string }
  /** The manuscript failed to compile. */
  | { case: 'latex-compile-failed'; lastGoodPdf?: boolean }
  /** The host grants no write access to this workspace. */
  | { case: 'read-only-host'; reason?: string }
  /** A streamed response stopped part-way. */
  | { case: 'stream-interrupted'; partialKept?: boolean };

export interface ResearchStatePresentation {
  kind: AsyncStateKind;
  title: string;
  description: string;
  safety: SafetyNote;
  icon?: IconName;
}

/** Maps a case to its wording. Exported so tests and docs can enumerate every state. */
export function describeResearchState(state: ResearchStateCase): ResearchStatePresentation {
  switch (state.case) {
    case 'offline':
      return {
        kind: 'retryable',
        icon: 'wifi-off',
        title: 'You are offline',
        description:
          'The workspace, the corpus and your transcripts are local and still work. Model calls resume when the connection returns.',
        safety: { draft: 'safe', source: 'safe', note: 'Nothing was sent.' },
      };
    case 'provider-unavailable':
      return {
        kind: 'retryable',
        icon: 'cloud-off',
        title: `${state.provider ?? 'The model provider'} did not respond`,
        description:
          'No reply arrived, so nothing was recorded for this attempt. Try again, or choose another provider.',
        safety: { draft: 'safe', source: 'safe', note: 'Your message is still in the composer.' },
      };
    case 'attachment-unsupported':
      return {
        kind: 'blocked',
        icon: 'paperclip',
        title: `${state.filename ?? 'This attachment'} is not supported by the selected model`,
        description:
          state.reason ??
          'Choose a model that accepts this file type, or remove the attachment before sending.',
        safety: { draft: 'safe', source: 'safe', note: 'The file is untouched in the workspace.' },
      };
    case 'attachment-omitted':
      return {
        kind: 'partial',
        icon: 'paperclip',
        title: `${state.filename ?? 'An attachment'} was left out of the context`,
        description:
          state.reason ??
          'The context pack had no room for it. The context receipt lists exactly what was and was not sent.',
        safety: { draft: 'safe', source: 'safe', note: 'The file is still attached to the session.' },
      };
    case 'egress-blocked':
      return {
        kind: 'blocked',
        icon: 'shield-off',
        title: 'A privacy rule blocked this request',
        description: state.policy
          ? `${state.policy} prevents this content from leaving the workspace. Change the session privacy class or remove the restricted content.`
          : 'The session privacy class prevents this content from leaving the workspace. Change the class or remove the restricted content.',
        safety: { draft: 'safe', source: 'safe', note: 'Nothing left the workspace.' },
      };
    case 'index-rebuilding':
      return {
        kind: 'loading',
        icon: 'refresh-cw',
        title: 'Rebuilding the research index',
        description:
          'Search and graph results are incomplete until the rebuild finishes. Accepted research objects are not affected - the index is derived and disposable.',
        safety: { source: 'safe', note: 'No accepted claim, evidence or artifact changes during a rebuild.' },
      };
    case 'index-absent':
      return {
        kind: 'partial',
        icon: 'hard-drive',
        title: 'The research index has not been built yet',
        description:
          'Search and graph results are answering from the canonical files, which cover less ' +
          'than the index does. Nothing is missing from the workspace - the index is derived ' +
          'and disposable, and has simply never been built here.',
        safety: {
          source: 'safe',
          note: 'Building it changes no accepted claim, evidence or artifact.',
        },
      };
    case 'index-unreadable':
      return {
        kind: 'partial',
        icon: 'circle-dashed',
        title: 'The research index is not answering',
        description:
          'Search and graph results are answering from the canonical files instead. Nothing is ' +
          'lost: the index is derived and disposable, and a rebuild produces it again from ' +
          'those files.',
        safety: {
          source: 'safe',
          note: 'No accepted claim, evidence or artifact is affected.',
        },
      };
    case 'anchor-stale':
      return {
        kind: 'stale',
        icon: 'clock',
        title: state.anchor
          ? `The anchor ${state.anchor} no longer matches its source`
          : 'This source anchor no longer matches its source',
        description:
          'The document changed after this anchor was recorded, so the highlighted region may point at different text. Re-anchor it against the current document before relying on it.',
        safety: {
          source: 'at-risk',
          note: 'The stored evidence and its recorded quote are unchanged.',
        },
      };
    case 'latex-compile-failed':
      return {
        kind: 'retryable',
        icon: 'alert-circle',
        title: 'The manuscript did not compile',
        description: state.lastGoodPdf
          ? 'The last PDF that compiled is still shown and is marked stale. Fix the reported diagnostics and compile again.'
          : 'No PDF has been produced yet. Fix the reported diagnostics and compile again.',
        safety: { draft: 'safe', source: 'safe', note: 'Your LaTeX source is saved exactly as you wrote it.' },
      };
    case 'read-only-host':
      return {
        kind: 'blocked',
        icon: 'lock',
        title: 'This workspace is read-only here',
        description:
          state.reason ??
          'The host has not granted write access, so edits, promotions and saves cannot be recorded.',
        safety: {
          draft: 'at-risk',
          source: 'safe',
          note: 'Copy anything you have written before leaving this view.',
        },
      };
    case 'stream-interrupted':
      return {
        kind: 'partial',
        icon: 'circle-dashed',
        title: 'The response was interrupted',
        description:
          state.partialKept === false
            ? 'The connection dropped before any of the reply could be kept.'
            : 'Part of the reply arrived before the connection dropped. It is kept in the transcript and marked partial.',
        safety: {
          draft: 'safe',
          source: 'safe',
          note: 'Nothing was accepted into the corpus from a partial reply.',
        },
      };
  }
}

export interface ResearchStateProps
  extends Omit<AsyncStateProps, 'kind' | 'title' | 'description' | 'safety' | 'icon'> {
  state: ResearchStateCase;
  /** Recovery actions supplied by the application. */
  actions?: readonly StateAction[];
  /** Overrides the preset wording when a surface needs to be more specific. */
  title?: ReactNode;
  description?: ReactNode;
}

/**
 * Renders one of the named research states. It is a thin, typed wrapper over
 * {@link AsyncState}: it chooses the kind, wording, icon and safety statement, and still
 * leaves every action to the caller.
 */
export const ResearchState = forwardRef<HTMLDivElement, ResearchStateProps>(
  function ResearchState({ state, title, description, ...rest }, ref) {
    const presentation = describeResearchState(state);
    return (
      <AsyncState
        ref={ref}
        kind={presentation.kind}
        icon={presentation.icon}
        title={title ?? presentation.title}
        description={description ?? presentation.description}
        safety={presentation.safety}
        data-case={state.case}
        progress={
          state.case === 'index-rebuilding'
            ? { value: state.progress, label: 'Index rebuild' }
            : undefined
        }
        {...rest}
      />
    );
  },
);
