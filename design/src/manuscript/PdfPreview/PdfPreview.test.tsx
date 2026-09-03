import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { PdfPreview } from './PdfPreview';
import type { BuildModel } from '../models';

const good: BuildModel = {
  buildId: 'B0007',
  status: 'succeeded',
  engine: 'latexmk -pdf',
  startedAt: '2026-09-03T10:00:00Z',
  finishedAt: '2026-09-03T10:00:12Z',
  pdf: { url: '/builds/B0007/pdf', stale: false, producedAt: '2026-09-03T10:00:12Z' },
  synctex: 'available',
};

const stale: BuildModel = {
  ...good,
  status: 'failed',
  pdf: { url: '/builds/B0006/pdf', stale: true, producedAt: '2026-09-03T09:41:00Z' },
  lastGood: { url: '/builds/B0006/pdf', producedAt: '2026-09-03T09:41:00Z' },
};

describe('PdfPreview', () => {
  it('pages through the document and reports where it is', async () => {
    const user = userEvent.setup();
    const onPageChange = vi.fn();
    render(<PdfPreview build={good} pageCount={12} defaultPage={1} onPageChange={onPageChange} />);

    expect(screen.getByText('Page 1 of 12')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(onPageChange).toHaveBeenLastCalledWith(2);
    expect(screen.getByText('Page 2 of 12')).toBeInTheDocument();
  });

  it('pages from the keyboard inside the page region', async () => {
    const user = userEvent.setup();
    render(<PdfPreview build={good} pageCount={4} />);
    const surface = screen.getByRole('group', { name: 'PDF preview pages' });
    surface.focus();

    await user.keyboard('{PageDown}');
    expect(screen.getByText('Page 2 of 4')).toBeInTheDocument();
    await user.keyboard('{End}');
    expect(screen.getByText('Page 4 of 4')).toBeInTheDocument();
    await user.keyboard('{Home}');
    expect(screen.getByText('Page 1 of 4')).toBeInTheDocument();
  });

  it('zooms and fits', async () => {
    const user = userEvent.setup();
    render(<PdfPreview build={good} pageCount={2} defaultScale={1} />);
    await user.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(screen.getByText('125%')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Fit page' }));
    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  it('labels a stale PDF with the time it was produced', () => {
    render(<PdfPreview build={stale} pageCount={12} />);
    expect(
      screen.getByText(
        'Showing the last successful PDF from 2026-09-03 09:41 UTC; the current build failed.',
      ),
    ).toBeInTheDocument();
  });

  it('shows the host setup guidance rather than a blank pane when no toolchain exists', () => {
    render(
      <PdfPreview
        build={{ status: 'unavailable', synctex: 'unavailable', setupGuidance: 'Install tectonic.' }}
      />,
    );
    expect(screen.getByText('No LaTeX toolchain is available')).toBeInTheDocument();
    expect(screen.getByText('Install tectonic.')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'PDF preview pages' })).not.toBeInTheDocument();
  });

  it('renders the application page slot and reports inverse sync', async () => {
    const user = userEvent.setup();
    const onInverseSync = vi.fn();
    const renderPage = vi.fn((index: number, scale: number) => (
      <div data-testid="page">{`pdf.js page ${index} at ${scale}`}</div>
    ));
    render(
      <PdfPreview
        build={good}
        pageCount={3}
        defaultPage={2}
        renderPage={renderPage}
        onInverseSync={onInverseSync}
      />,
    );
    expect(screen.getByTestId('page')).toHaveTextContent('pdf.js page 2 at 1');

    await user.dblClick(screen.getByRole('group', { name: 'PDF preview pages' }));
    expect(onInverseSync).toHaveBeenCalledWith(2, 0, 0);
  });

  it('submits a search query', async () => {
    const user = userEvent.setup();
    const onSearch = vi.fn();
    render(<PdfPreview build={good} pageCount={3} onSearch={onSearch} />);
    await user.type(screen.getByLabelText('Search the PDF'), 'variance{Enter}');
    expect(onSearch).toHaveBeenCalledWith('variance');
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <PdfPreview build={stale} pageCount={12} onSearch={vi.fn()} onInverseSync={vi.fn()} />,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('PdfPreview', () => (
  <PdfPreview build={stale} pageCount={12} defaultPage={3} />
));
