import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { FullPageWorkspace } from './FullPageWorkspace';

describe('FullPageWorkspace', () => {
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
