import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SourceEditorFrame } from './SourceEditorFrame';
import type { EditorFrameState } from '../models';

const clean: EditorFrameState = {
  path: 'manuscript/main.tex',
  dirty: false,
  cursor: { line: 42, column: 7 },
};

describe('SourceEditorFrame', () => {
  it('frames the editor engine and names the open file', () => {
    render(
      <SourceEditorFrame state={clean}>
        <div data-testid="engine">CodeMirror</div>
      </SourceEditorFrame>,
    );
    expect(
      screen.getByRole('region', { name: 'Manuscript source: manuscript/main.tex' }),
    ).toBeInTheDocument();
    expect(screen.getByTestId('engine')).toBeInTheDocument();
    expect(screen.getByText('Ln 42, Col 7')).toBeInTheDocument();
    expect(screen.getByText('Saved')).toBeInTheDocument();
  });

  it('says unsaved, conflicted and read-only in words', () => {
    render(
      <SourceEditorFrame
        state={{
          path: 'manuscript/main.tex',
          dirty: true,
          conflict: { message: 'The file changed on disk since you opened it.' },
          readOnly: true,
          readOnlyReason: 'the workspace is mounted read-only',
        }}
      />,
    );
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
    expect(screen.getByText('Changed on disk')).toBeInTheDocument();
    expect(screen.getByText('Read-only: the workspace is mounted read-only')).toBeInTheDocument();
  });

  it('documents Ctrl/Cmd+S on Save and calls back on Save and Compile', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const onCompile = vi.fn();
    render(<SourceEditorFrame state={{ ...clean, dirty: true }} onSave={onSave} onCompile={onCompile} />);

    const save = screen.getByRole('button', { name: 'Save' });
    expect(save).toHaveAttribute('aria-keyshortcuts', 'Control+S Meta+S');
    await user.click(save);
    expect(onSave).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Compile' }));
    expect(onCompile).toHaveBeenCalledTimes(1);
  });

  /**
   * The third critique's minor observation: the reason there is no SyncTeX map held a row of
   * its own above the editor for the whole session, whether or not anyone ever tried to
   * jump. The reason is now an answer to the attempt — and the assertions that encoded the
   * permanent row changed with it, on purpose: the control is pressable so that it can
   * answer, and the row does not exist until it does.
   */
  it('says why a jump did nothing, and only once one is attempted', async () => {
    const user = userEvent.setup();
    const onSyncForward = vi.fn();
    render(
      <SourceEditorFrame
        state={clean}
        onSyncForward={onSyncForward}
        synctex="unavailable"
        synctexReason="this build produced no .synctex.gz"
      />,
    );

    expect(screen.queryByText(/SyncTeX/)).toBeNull();
    const jump = screen.getByRole('button', { name: 'Jump to PDF' });
    await user.click(jump);

    expect(onSyncForward, 'a jump that cannot land is not attempted').not.toHaveBeenCalled();
    const note = document.querySelector('.rh-source-editor__note') as HTMLElement;
    expect(note).toHaveTextContent(
      'Jump to PDF has nothing to point at: this build produced no .synctex.gz.',
    );
    expect(note, 'the answer is announced politely').toHaveAttribute('role', 'status');
    expect(jump).toHaveAttribute('aria-describedby', note.id);
  });

  it('jumps, and says nothing, when the build has a map', async () => {
    const user = userEvent.setup();
    const onSyncForward = vi.fn();
    render(<SourceEditorFrame state={clean} onSyncForward={onSyncForward} />);

    await user.click(screen.getByRole('button', { name: 'Jump to PDF' }));

    expect(onSyncForward).toHaveBeenCalledTimes(1);
    expect(document.querySelector('.rh-source-editor__note')).toBeNull();
  });

  /**
   * Save was enabled on a buffer whose own chip read "Saved" — a control offering an act
   * with nothing to act on (third critique, minor). The chip is the reason, so the button
   * points at it rather than growing a second sentence beside it.
   */
  it('disables Save when there is nothing to save, and points at the reason', () => {
    render(<SourceEditorFrame state={clean} onSave={vi.fn()} />);

    const save = screen.getByRole('button', { name: 'Save' });
    expect(save).toBeDisabled();
    const reason = document.getElementById(save.getAttribute('aria-describedby') ?? '');
    expect(reason).toHaveTextContent('Saved');
  });

  it('enables Save the moment there is something to save', () => {
    render(<SourceEditorFrame state={{ ...clean, dirty: true }} onSave={vi.fn()} />);

    const save = screen.getByRole('button', { name: 'Save' });
    expect(save).toBeEnabled();
    expect(save).not.toHaveAttribute('aria-describedby');
  });

  it('keeps a read-only buffer’s own reason on the disabled Save', () => {
    render(
      <SourceEditorFrame
        state={{
          ...clean,
          dirty: true,
          readOnly: true,
          readOnlyReason: 'this window is an agent host',
        }}
        onSave={vi.fn()}
      />,
    );

    const save = screen.getByRole('button', { name: 'Save' });
    expect(save).toBeDisabled();
    const reason = document.getElementById(save.getAttribute('aria-describedby') ?? '');
    expect(reason).toHaveTextContent('Read-only: this window is an agent host');
  });

  it('offers both answers to a conflict and never resolves it itself', async () => {
    const user = userEvent.setup();
    const onReloadFromDisk = vi.fn();
    const onKeepMine = vi.fn();
    render(
      <SourceEditorFrame
        state={{ ...clean, dirty: true, conflict: { message: 'Changed under your edit.' } }}
        onReloadFromDisk={onReloadFromDisk}
        onKeepMine={onKeepMine}
      />,
    );
    expect(screen.getByText('Your draft is not saved yet. The source may have changed.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Reload from disk' }));
    await user.click(screen.getByRole('button', { name: 'Keep mine' }));
    expect(onReloadFromDisk).toHaveBeenCalledTimes(1);
    expect(onKeepMine).toHaveBeenCalledTimes(1);
  });

  it('shows an empty state with no file open', () => {
    render(<SourceEditorFrame state={{ dirty: false }} />);
    expect(screen.getAllByText('No file open').length).toBeGreaterThan(0);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <SourceEditorFrame
        state={{ ...clean, dirty: true, conflict: { message: 'Changed under your edit.' } }}
        onSave={vi.fn()}
        onCompile={vi.fn()}
        onSyncForward={vi.fn()}
        synctex="unavailable"
        synctexReason="no mapping"
        onReloadFromDisk={vi.fn()}
        onKeepMine={vi.fn()}
      >
        <textarea aria-label="Source" defaultValue="\\documentclass{article}" />
      </SourceEditorFrame>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('SourceEditorFrame', () => (
  <SourceEditorFrame state={{ ...clean, dirty: true }} onSave={() => undefined} onCompile={() => undefined}>
    <pre>{'\\section{Results}'}</pre>
  </SourceEditorFrame>
));
