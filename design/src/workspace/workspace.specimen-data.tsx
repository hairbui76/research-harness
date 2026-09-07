/**
 * Fixtures shared by the workspace specimens. Not part of the published package —
 * `tsconfig.build.json` excludes `src/**\/*.specimen*` from `dist`.
 */
import type { ReactElement } from 'react';
import type { ProjectModel, ProviderStatus, RailItem } from './models';

export const project: ProjectModel = {
  id: 'P1',
  name: 'Thermal tolerance',
  path: '/home/researcher/projects/thermal',
};

export const projects: ProjectModel[] = [
  project,
  { id: 'P2', name: 'Reef survey', path: '/home/researcher/projects/reef' },
];

/** Three named runs, in the order the rail reads them, and the two ways in above them. */
export const railItems: RailItem[] = [
  { id: 'corpus', label: 'Corpus', to: '#corpus', icon: 'library', group: 'The record' },
  {
    id: 'claims',
    label: 'Claims',
    to: '#claims',
    icon: 'bookmark',
    active: true,
    group: 'The record',
  },
  {
    id: 'questions',
    label: 'Questions',
    to: '#questions',
    icon: 'circle-help',
    group: 'The record',
  },
  { id: 'synthesis', label: 'Synthesis', to: '#synthesis', icon: 'layers', group: 'Outputs' },
  {
    id: 'manuscript',
    label: 'Manuscript',
    to: '#manuscript',
    icon: 'file-code',
    group: 'Outputs',
  },
  { id: 'review', label: 'Review inbox', icon: 'inbox', count: 4, group: 'Waiting' },
  { id: 'conflicts', label: 'Conflicts', icon: 'alert-triangle', count: 1, group: 'Waiting' },
  { id: 'stale', label: 'Stale', icon: 'clock', count: 3, group: 'Waiting' },
];

export const providerOk: ProviderStatus = {
  label: 'Local Ollama',
  state: 'ok',
  detail: 'llama3.1:8b, 127.0.0.1:11434',
};

export const providerOffline: ProviderStatus = {
  label: 'Local Ollama',
  state: 'offline',
  detail: 'No response on 127.0.0.1:11434',
};

export function SessionList(): ReactElement {
  const sessions = [
    { id: 'CS0003', title: 'Acclimation window', when: 'today' },
    { id: 'CS0002', title: 'Reviewer 2 on the load model', when: 'yesterday' },
    { id: 'CS0001', title: 'First pass over Smith 2024', when: '2 days ago' },
  ];
  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {sessions.map((session) => (
        <li key={session.id}>
          <button
            type="button"
            style={{
              display: 'block',
              inlineSize: '100%',
              padding: 'var(--rh-space-2)',
              border: 0,
              borderRadius: 'var(--rh-radius-nav)',
              background: 'transparent',
              color: 'var(--rh-text-secondary)',
              font: 'inherit',
              textAlign: 'start',
              cursor: 'pointer',
            }}
          >
            <span style={{ display: 'block', color: 'var(--rh-text-primary)' }}>
              {session.title}
            </span>
            <span style={{ fontFamily: 'var(--rh-font-mono)', fontSize: 'var(--rh-type-mono-size)' }}>
              {`${session.id} · ${session.when}`}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function Transcript(): ReactElement {
  return (
    <ol style={{ listStyle: 'none', margin: 0, padding: 'var(--rh-space-4)', display: 'grid', gap: 'var(--rh-space-4)' }}>
      <li>
        <p style={{ margin: 0, fontFamily: 'var(--rh-font-mono)', fontSize: 'var(--rh-type-mono-size)', color: 'var(--rh-text-muted)' }}>
          M0041 · you
        </p>
        <p style={{ margin: 0 }}>Does acclimation temperature change the thermal maximum in @W0017?</p>
      </li>
      <li>
        <p style={{ margin: 0, fontFamily: 'var(--rh-font-mono)', fontSize: 'var(--rh-type-mono-size)', color: 'var(--rh-text-muted)' }}>
          M0042 · assistant
        </p>
        <p style={{ margin: 0 }}>
          The accepted evidence E0482 records a 2.1 °C shift across the acclimation range. The
          transcript above disagrees; accepted state wins, and the discrepancy is listed in the
          context receipt.
        </p>
      </li>
    </ol>
  );
}

export function Composer(): ReactElement {
  return (
    <div style={{ padding: 'var(--rh-space-3)', display: 'grid', gap: 'var(--rh-space-2)' }}>
      <label style={{ display: 'grid', gap: 'var(--rh-space-1)' }}>
        <span className="rh-visually-hidden">Message</span>
        <textarea
          rows={3}
          placeholder="Ask about the corpus, or @-reference an object"
          style={{
            inlineSize: '100%',
            padding: 'var(--rh-space-2)',
            border: 'var(--rh-border-width) solid var(--rh-border-strong)',
            borderRadius: 'var(--rh-radius-control)',
            background: 'var(--rh-surface-raised)',
            color: 'var(--rh-text-primary)',
            font: 'inherit',
          }}
        />
      </label>
      <div style={{ display: 'flex', gap: 'var(--rh-space-2)', justifyContent: 'flex-end' }}>
        <button type="button" className="rh-button rh-button--accent rh-button--sm">
          <span className="rh-button__content">
            <span className="rh-button__label">Send</span>
          </span>
        </button>
      </div>
    </div>
  );
}
