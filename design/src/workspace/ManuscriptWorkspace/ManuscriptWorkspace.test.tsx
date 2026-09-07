import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { ManuscriptWorkspace } from './ManuscriptWorkspace';
import type { PaneSizes } from '../models';

/** Stands in for CodeMirror: it holds state the workspace must not throw away. */
function Editor(): JSX.Element {
  const [source, setSource] = useState('\\section{Results}');
  return (
    <label>
      Source
      <textarea value={source} onChange={(event) => setSource(event.target.value)} />
    </label>
  );
}

/** Stands in for pdf.js: same point, for the page being read. */
function Preview(): JSX.Element {
  const [page, setPage] = useState(1);
  return (
    <div>
      <p>{`Page ${page}`}</p>
      <button type="button" onClick={() => setPage(page + 1)}>
        Next page
      </button>
    </div>
  );
}

function Example(props: { narrow?: boolean; onColumnSizesChange?: (s: PaneSizes) => void }) {
  return (
    <ManuscriptWorkspace
      narrow={props.narrow}
      onColumnSizesChange={props.onColumnSizesChange}
      fileTree={<nav aria-label="Files">main.tex</nav>}
      editor={<Editor />}
      preview={<Preview />}
      inspector={<p>Compiler diagnostics and audit</p>}
    />
  );
}

describe('ManuscriptWorkspace', () => {
  // One test supplies `ResizeObserver` and a layout engine jsdom does not have; the stubs
  // must not outlive it, or every later test would be measuring that one's element.
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('lays files, source and PDF out as three panes on a wide screen', () => {
    render(<Example narrow={false} />);
    expect(screen.getByRole('navigation', { name: 'Files' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Source' })).toBeInTheDocument();
    expect(screen.getByText('Page 1')).toBeInTheDocument();
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
  });

  it('collapses and reopens the audit inspector', async () => {
    const user = userEvent.setup();
    render(<Example narrow={false} />);
    const toggle = screen.getByRole('button', { name: 'Collapse the build and audit panel' });
    expect(screen.getByRole('region', { name: 'Build and audit' })).toBeInTheDocument();

    await user.click(toggle);
    expect(screen.queryByRole('region', { name: 'Build and audit' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Expand the build and audit panel' }));
    expect(screen.getByRole('region', { name: 'Build and audit' })).toBeInTheDocument();
  });

  it('turns the editor and preview into tabs below the breakpoint', () => {
    render(<Example narrow />);
    expect(screen.getByRole('tablist', { name: 'Manuscript view' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Source' })).toHaveAttribute('aria-selected', 'true');
  });

  it('keeps both tab panels mounted so cursor and page position survive a switch', async () => {
    const user = userEvent.setup();
    render(<Example narrow />);

    await user.clear(screen.getByRole('textbox', { name: 'Source' }));
    await user.type(screen.getByRole('textbox', { name: 'Source' }), 'edited source');

    await user.click(screen.getByRole('tab', { name: 'PDF' }));
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByText('Page 2')).toBeInTheDocument();
    // The editor is hidden from assistive technology but still mounted, so its buffer is
    // still there — an unmounted CodeMirror would have lost it.
    expect(screen.getByLabelText('Source', { selector: 'textarea' })).toHaveValue(
      'edited source',
    );

    await user.click(screen.getByRole('tab', { name: 'Source' }));
    expect(screen.getByRole('textbox', { name: 'Source' })).toHaveValue('edited source');
    // …and the preview kept the page the researcher was reading.
    expect(screen.getByText('Page 2')).toBeInTheDocument();
  });

  it('reports column sizes keyed by pane', async () => {
    const user = userEvent.setup();
    const onColumnSizesChange = vi.fn();
    render(<Example narrow={false} onColumnSizesChange={onColumnSizesChange} />);

    const [filesHandle] = screen.getAllByRole('separator');
    filesHandle?.focus();
    await user.keyboard('{ArrowRight}');

    const sizes = onColumnSizesChange.mock.calls.at(-1)?.[0] as PaneSizes;
    expect(Object.keys(sizes).sort()).toEqual(['editor', 'files', 'preview']);
  });

  it('gives the audit inspector the whole document area below the breakpoint', async () => {
    const user = userEvent.setup();
    render(<Example narrow />);

    // Three views of one area, not three panes dividing a width none of them can hold.
    const views = screen.getByRole('tablist', { name: 'Manuscript view' });
    expect(within(views).getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Source',
      'PDF',
      'Build and audit',
    ]);
    // While the source is showing, the inspector is not a second region under it.
    expect(screen.queryByRole('region', { name: 'Build and audit' })).not.toBeInTheDocument();

    await user.click(within(views).getByRole('tab', { name: 'Build and audit' }));
    expect(screen.getByRole('region', { name: 'Build and audit' })).toHaveTextContent(
      'Compiler diagnostics and audit',
    );
  });

  it('lets a host name the narrow tab when the inspector carries a strip of its own', () => {
    render(
      <ManuscriptWorkspace
        narrow
        view="inspector"
        inspectorTabLabel="Inspector"
        fileTree={<nav aria-label="Files">main.tex</nav>}
        editor={<Editor />}
        preview={<Preview />}
        inspector={<p>Compiler diagnostics and audit</p>}
      />,
    );
    const views = screen.getByRole('tablist', { name: 'Manuscript view' });
    expect(within(views).getByRole('tab', { name: 'Inspector' })).toBeInTheDocument();
    // The panel is still the panel: only the word on the tab changed.
    expect(screen.getByRole('region', { name: 'Build and audit' })).toBeInTheDocument();
  });

  it('keeps one inspector control in the bar at both widths', async () => {
    const user = userEvent.setup();
    render(<Example narrow />);

    const toggle = screen.getByRole('button', { name: 'Expand the build and audit panel' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(toggle);
    expect(screen.getByRole('region', { name: 'Build and audit' })).toBeInTheDocument();
    const open = screen.getByRole('button', { name: 'Collapse the build and audit panel' });
    expect(open).toHaveAttribute('aria-expanded', 'true');

    await user.click(open);
    expect(screen.queryByRole('region', { name: 'Build and audit' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Source' })).toBeInTheDocument();
  });

  it('reads its own width rather than the window’s', () => {
    // jsdom has no layout engine and no `ResizeObserver`, so both are supplied. The point
    // is the ruler: a 1024px window that spends 16rem on the project rail hands this
    // workspace about 768px, and a media query on the window would call that wide.
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        disconnect() {}
      },
    );
    const matchMedia = vi.fn();
    vi.stubGlobal('matchMedia', matchMedia);
    const rect = vi
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockReturnValue({ width: 768 } as DOMRect);

    const narrow = render(<Example />);
    expect(screen.getByRole('tablist', { name: 'Manuscript view' })).toBeInTheDocument();
    expect(matchMedia).not.toHaveBeenCalled();
    narrow.unmount();

    // …and an element nobody has laid out yet reports zero, which is not a small screen.
    rect.mockReturnValue({ width: 0 } as DOMRect);
    render(<Example />);
    expect(screen.queryByRole('tablist', { name: 'Manuscript view' })).not.toBeInTheDocument();
  });

  it('can place the inspector at the end instead of the bottom', () => {
    const { container } = render(
      <ManuscriptWorkspace
        narrow={false}
        inspectorPlacement="end"
        fileTree={<nav aria-label="Files">main.tex</nav>}
        editor={<Editor />}
        preview={<Preview />}
        inspector={<p>diagnostics</p>}
      />,
    );
    expect(container.firstChild).toHaveAttribute('data-inspector-placement', 'end');
    expect(screen.getByRole('complementary', { name: 'Build and audit' })).toBeInTheDocument();
  });

  it('has no axe violations, wide or narrow', async () => {
    const wide = render(<Example narrow={false} />);
    await expectNoAxeViolations(wide.container);
    wide.unmount();

    const narrow = render(<Example narrow />);
    await expectNoAxeViolations(narrow.container);
  });
});

describeThemeDensitySnapshots('ManuscriptWorkspace', () => (
  <ManuscriptWorkspace
    narrow={false}
    fileTree={<nav aria-label="Files">main.tex</nav>}
    editor={<p>editor</p>}
    preview={<p>preview</p>}
    inspector={<p>diagnostics</p>}
  />
));
