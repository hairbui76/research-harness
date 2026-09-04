/**
 * What the conversation keeps in `localStorage`, and who it belongs to.
 *
 * One browser origin now serves every project the researcher has opened (design §4.5), and
 * session ids are per-workspace: two projects both have a `CS0001`. So the composer draft
 * and the open run are keyed by project *and* session. A window with no project — the
 * legacy `research serve` host — keeps the key it has always used, which is the whole
 * reason an existing draft survives this change.
 *
 * The second rule these pin is the one design §11 states about routes: nothing already
 * prefixed with `/projects/{id}` is written to storage. A stored token carries the
 * workspace-local route it has always carried, and the prefix is put back when it is read.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { ProjectPathProvider } from '../../app/projectPaths';
import { draftKey, readDraft, useDraft } from './useDraft';
import { runKey } from './useSend';

function wrapper(projectId: string | null) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <ProjectPathProvider projectId={projectId}>{children}</ProjectPathProvider>;
  };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe('the draft key', () => {
  it('names the project as well as the session under a multi-project host', () => {
    expect(draftKey('CS0001', 'prj_abc')).toBe(
      'research-harness.conversation.draft.prj_abc.CS0001',
    );
  });

  it('is the key it has always been when there is no project', () => {
    expect(draftKey('CS0001')).toBe('research-harness.conversation.draft.CS0001');
    expect(draftKey('CS0001', null)).toBe('research-harness.conversation.draft.CS0001');
  });

  it('keeps two projects’ drafts for the same session id apart', () => {
    const { result } = renderHook(() => useDraft('CS0001'), { wrapper: wrapper('prj_abc') });
    act(() => result.current.setValue({ text: 'the reef draft', tokens: [] }));

    const other = renderHook(() => useDraft('CS0001'), { wrapper: wrapper('prj_xyz') });
    expect(other.result.current.value.text).toBe('');
    expect(readDraft('CS0001', 'prj_abc').text).toBe('the reef draft');
    expect(readDraft('CS0001', 'prj_xyz').text).toBe('');
  });

  it('still reads a draft written before there were projects', () => {
    const legacy = renderHook(() => useDraft('CS0001'), { wrapper: wrapper(null) });
    act(() => legacy.result.current.setValue({ text: 'typed under research serve', tokens: [] }));

    expect(
      window.localStorage.getItem('research-harness.conversation.draft.CS0001'),
    ).toContain('typed under research serve');
    expect(readDraft('CS0001').text).toBe('typed under research serve');
  });

  it('stores a token’s route workspace-local and hands it back inside the project', () => {
    const { result } = renderHook(() => useDraft('CS0001'), { wrapper: wrapper('prj_abc') });
    act(() =>
      result.current.setValue({
        text: 'about @E0482',
        tokens: [
          {
            id: 'E0482',
            kind: 'evidence',
            resolution: 'resolved',
            href: '/projects/prj_abc/evidence/E0482',
          },
        ],
      }),
    );

    const raw = window.localStorage.getItem('research-harness.conversation.draft.prj_abc.CS0001');
    expect(raw).toContain('/evidence/E0482');
    expect(raw).not.toContain('/projects/');
    expect(readDraft('CS0001', 'prj_abc').tokens[0]?.href).toBe(
      '/projects/prj_abc/evidence/E0482',
    );
  });
});

describe('the run key', () => {
  it('names the project as well as the session under a multi-project host', () => {
    expect(runKey('CS0001', 'prj_abc')).toBe('research-harness.conversation.run.prj_abc.CS0001');
  });

  it('is the key it has always been when there is no project', () => {
    expect(runKey('CS0001')).toBe('research-harness.conversation.run.CS0001');
    expect(runKey('CS0001', null)).toBe('research-harness.conversation.run.CS0001');
  });
});
