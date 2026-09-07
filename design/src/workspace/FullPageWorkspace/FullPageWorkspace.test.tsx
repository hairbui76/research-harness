import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { FullPageWorkspace } from './FullPageWorkspace';

describe('FullPageWorkspace', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.style.removeProperty('--rh-page-header-bottom');
  });

  it('makes the title the page heading and names the region with it', () => {
    const { container } = render(
      <FullPageWorkspace title="Corpus" description="Every artifact in this project">
        <table>
          <tbody>
            <tr>
              <td>A0017</td>
            </tr>
          </tbody>
        </table>
      </FullPageWorkspace>,
    );
    const heading = screen.getByRole('heading', { level: 1, name: 'Corpus' });
    expect(heading).toBeInTheDocument();
    expect(container.firstChild).toHaveAttribute('aria-labelledby', heading.id);
    expect(screen.getByText('Every artifact in this project')).toBeInTheDocument();
  });

  it('renders the toolbar, the side panel and the footer slots', () => {
    render(
      <FullPageWorkspace
        title="Claims"
        toolbar={<button type="button">Filter</button>}
        sidePanel={<p>Facets</p>}
        sidePanelLabel="Facets"
        footer={<p>41 claims</p>}
      >
        <p>rows</p>
      </FullPageWorkspace>,
    );
    expect(screen.getByRole('button', { name: 'Filter' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Facets' })).toBeInTheDocument();
    expect(screen.getByText('41 claims')).toBeInTheDocument();
  });

  it('puts the side panel on the requested edge', () => {
    const { container } = render(
      <FullPageWorkspace title="Synthesis" sidePanel={<p>outline</p>} sidePanelPosition="start">
        <p>body</p>
      </FullPageWorkspace>,
    );
    expect(container.firstChild).toHaveAttribute('data-side', 'start');
  });

  it('marks the content region busy while the body is still arriving', () => {
    const { container, rerender } = render(
      <FullPageWorkspace title="Corpus" busy>
        <p>a skeleton</p>
      </FullPageWorkspace>,
    );
    // The frame stays: the heading a screen-reader user lands on is there before the data.
    expect(screen.getByRole('heading', { level: 1, name: 'Corpus' })).toBeInTheDocument();
    expect(container.querySelector('.rh-full-page__content')).toHaveAttribute('aria-busy', 'true');

    rerender(
      <FullPageWorkspace title="Corpus">
        <p>the rows</p>
      </FullPageWorkspace>,
    );
    expect(container.querySelector('.rh-full-page__content')).not.toHaveAttribute('aria-busy');
  });

  it('publishes where its header ends, so a fixed overlay can start there', () => {
    // jsdom has no `ResizeObserver` and no layout engine, so both are supplied: the edge is
    // whatever the observed element reports, and the point of the test is that the frame
    // publishes it on the root and takes it back down again. The toast viewport is the
    // reason — it is portalled outside this frame and cannot read a value scoped to it.
    //
    // The *bottom* edge, not the height: a research page stacks the shell's bar and the
    // project's breadcrumb above this header, and an overlay offset by heights it happens
    // to know about lands on the one it does not.
    const observed: Element[] = [];
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe(node: Element) {
          observed.push(node);
        }
        disconnect() {}
      },
    );
    const root = document.documentElement;
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      bottom: 178,
      height: 96,
    } as DOMRect);

    const { container, unmount } = render(<FullPageWorkspace title="Corpus">rows</FullPageWorkspace>);
    expect(root.style.getPropertyValue('--rh-page-header-bottom')).toBe('178px');
    expect(observed).toEqual([container.querySelector('.rh-full-page__header')]);

    unmount();
    expect(root.style.getPropertyValue('--rh-page-header-bottom')).toBe('');
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <FullPageWorkspace
        title="Corpus"
        description="Every artifact"
        toolbar={<button type="button">Filter</button>}
        sidePanel={<p>Facets</p>}
        sidePanelLabel="Facets"
      >
        <p>rows</p>
      </FullPageWorkspace>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('FullPageWorkspace', () => (
  <FullPageWorkspace
    title="Corpus"
    description="Every artifact in this project"
    toolbar={<button type="button">Filter</button>}
    sidePanel={<p>Facets</p>}
    sidePanelLabel="Facets"
  >
    <p>rows</p>
  </FullPageWorkspace>
));
