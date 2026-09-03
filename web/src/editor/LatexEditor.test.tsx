/**
 * The source editor's contract with the manuscript workspace.
 *
 * The properties that matter to W4 are the ones a cursor and a save depend on: an external
 * value that has not changed must not move the cursor, `Mod-s` must be the *only* way a
 * save is asked for, the cursor must be reported in the 1-based lines SyncTeX speaks, and
 * `goTo` must land on the line a compiler diagnostic named.
 *
 * CodeMirror measures the document as it renders, which jsdom cannot do; the two `Range`
 * shims below are the whole accommodation, and they live here rather than in `setup.ts`
 * because no other test needs them.
 */
import { createRef } from 'react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LatexEditor } from './LatexEditor';
import type { LatexEditorHandle } from './LatexEditor';

beforeAll(() => {
  const rect = {
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: 0,
    height: 0,
    toJSON: () => ({}),
  } as DOMRect;
  const rects = Object.assign([] as DOMRect[], { item: () => null }) as unknown as DOMRectList;
  Range.prototype.getClientRects = function getClientRects() {
    return rects;
  };
  Range.prototype.getBoundingClientRect = function getBoundingClientRect() {
    return rect;
  };
});

const SOURCE = ['% the introduction', '\\section{Method}', 'We estimate $\\beta$ by OLS.'].join(
  '\n',
);

function mount(props: Partial<Parameters<typeof LatexEditor>[0]> = {}) {
  const handle = createRef<LatexEditorHandle>();
  const view = render(
    <LatexEditor ref={handle} value={props.value ?? SOURCE} fileName="main.tex" {...props} />,
  );
  return { handle, ...view };
}

describe('LatexEditor', () => {
  it('shows the source with line numbers and a name', () => {
    const { container } = mount();

    const editor = screen.getByRole('textbox', { name: 'main.tex source' });
    expect(editor).toHaveTextContent('\\section{Method}');
    expect(container.querySelector('.cm-gutters')).not.toBeNull();
    expect(container.querySelectorAll('.cm-lineNumbers .cm-gutterElement').length).toBeGreaterThan(
      1,
    );
  });

  it('marks LaTeX comments, commands and maths delimiters', () => {
    const { container } = mount();
    expect(container.querySelector('.rh-tex-comment')?.textContent).toBe('% the introduction');
    expect(container.querySelector('.rh-tex-command')?.textContent).toBe('\\section');
    expect(container.querySelector('.rh-tex-math')?.textContent).toBe('$');
  });

  it('picks the mode from the file name', () => {
    const { container } = mount({ value: '@article{smith2020,\n  title = {A paper},\n}', fileName: 'refs.bib' });
    expect(container.querySelector('.rh-editor')).toHaveAttribute('data-language', 'bibtex');
    expect(container.querySelector('.rh-tex-command')?.textContent).toBe('@article');
  });

  it('reports every edit as the whole document', () => {
    const onChange = vi.fn();
    const { handle } = mount({ onChange });

    act(() => {
      handle.current?.getView()?.dispatch({ changes: { from: 0, insert: '\\input{preamble}\n' } });
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0]![0]).toBe(`\\input{preamble}\n${SOURCE}`);
    expect(handle.current?.getValue()).toBe(`\\input{preamble}\n${SOURCE}`);
  });

  it('leaves the cursor alone when the value it is given has not changed', () => {
    const { handle, rerender } = mount();
    act(() => handle.current!.goTo(3, 4));
    const before = handle.current!.getCursor();
    expect(before).toEqual({ line: 3, column: 4 });

    // The parent re-renders with the same text — the keystroke round trip every controlled
    // editor makes. Nothing may be dispatched, or the cursor moves under the researcher.
    rerender(<LatexEditor ref={handle} value={SOURCE} fileName="main.tex" />);

    expect(handle.current!.getCursor()).toEqual(before);
    expect(handle.current!.getView()!.state.selection.main.head).toBe(
      handle.current!.getView()!.state.doc.line(3).from + 3,
    );
  });

  it('takes an external change and clamps the cursor into the new document', () => {
    const { handle, rerender } = mount();
    act(() => handle.current!.goTo(3, 20));

    rerender(<LatexEditor ref={handle} value="short" fileName="main.tex" />);

    expect(handle.current!.getValue()).toBe('short');
    expect(handle.current!.getView()!.state.selection.main.head).toBeLessThanOrEqual(5);
  });

  it('reports the cursor as a 1-based line and column', () => {
    const onCursorChange = vi.fn();
    const { handle } = mount({ onCursorChange });

    act(() => handle.current!.goTo(2, 1));

    expect(handle.current!.getCursor()).toEqual({ line: 2, column: 1 });
    expect(onCursorChange).toHaveBeenLastCalledWith({ line: 2, column: 1 });
  });

  it('lands on the line a diagnostic names, and clamps one that is out of range', () => {
    const { handle } = mount();

    act(() => handle.current!.goTo(999));

    // Line 3 is the last; a stale diagnostic must not throw.
    expect(handle.current!.getCursor().line).toBe(3);
    expect(handle.current!.getView()!.hasFocus).toBe(true);
  });

  it('asks the caller to save on Mod-s, and saves nothing itself', async () => {
    const onSave = vi.fn();
    const onChange = vi.fn();
    mount({ onSave, onChange });

    const editor = screen.getByRole('textbox', { name: 'main.tex source' });
    act(() => editor.focus());
    await userEvent.keyboard('{Control>}s{/Control}');

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith(SOURCE);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('says why it is read-only, and refuses to be typed into', () => {
    const { handle } = mount({
      readOnly: true,
      readOnlyReason: 'main.tex changed on disk; reload it before editing.',
    });

    expect(screen.getByRole('status')).toHaveTextContent('changed on disk');
    const editor = screen.getByRole('textbox', { name: 'main.tex source' });
    expect(editor).toHaveAttribute('contenteditable', 'false');
    expect(editor).toHaveAttribute('aria-readonly', 'true');
    expect(handle.current!.getView()!.state.readOnly).toBe(true);
  });

  it('opens the search panel from the keyboard', async () => {
    const { container } = mount();
    const editor = screen.getByRole('textbox', { name: 'main.tex source' });
    act(() => editor.focus());

    await userEvent.keyboard('{Control>}f{/Control}');

    expect(container.querySelector('.cm-search')).not.toBeNull();
  });
});
