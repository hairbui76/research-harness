import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { SAMPLE_FAILED_ATTACHMENT, SAMPLE_PDF } from '../samples';
import { PdfAttachment } from './PdfAttachment';

describe('PdfAttachment', () => {
  it('shows the name, the size, the page count and the state', () => {
    render(<PdfAttachment attachment={SAMPLE_PDF} />);
    expect(screen.getByText(SAMPLE_PDF.name)).toBeInTheDocument();
    expect(screen.getByText('3.4 MB')).toBeInTheDocument();
    expect(screen.getByText('14 pages')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });

  it('says plainly that a preview is not corpus ingestion', async () => {
    const user = userEvent.setup();
    render(<PdfAttachment attachment={SAMPLE_PDF} renderPage={() => <p>page</p>} />);
    await user.click(screen.getByRole('button', { name: `Preview ${SAMPLE_PDF.name}` }));
    expect(
      screen.getByText(/does not add it to the corpus and does not create evidence/i),
    ).toBeInTheDocument();
  });

  it('draws pages with the renderer the application supplies', async () => {
    const user = userEvent.setup();
    const renderPage = vi.fn((index: number) => <p>page {index + 1}</p>);
    render(<PdfAttachment attachment={SAMPLE_PDF} renderPage={renderPage} defaultOpen />);
    expect(screen.getByText('page 1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByText('page 2')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Page 2 of 14');
  });

  it('stops at the first and last page', async () => {
    const user = userEvent.setup();
    render(
      <PdfAttachment
        attachment={{ ...SAMPLE_PDF, pageCount: 2 }}
        renderPage={() => <p>page</p>}
        defaultOpen
      />,
    );
    expect(screen.getByRole('button', { name: 'Previous page' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
  });

  it('stays useful when no page renderer exists', () => {
    render(<PdfAttachment attachment={SAMPLE_PDF} defaultOpen />);
    expect(screen.getByText(/No page renderer is available here/)).toBeInTheDocument();
    expect(screen.getByText(/still be downloaded/)).toBeInTheDocument();
  });

  it('marks a failed attachment without hiding it', () => {
    const { container } = render(<PdfAttachment attachment={SAMPLE_FAILED_ATTACHMENT} />);
    expect(container.querySelector('.rh-attachment-card')).toHaveAttribute('data-state', 'failed');
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText(SAMPLE_FAILED_ATTACHMENT.name)).toBeInTheDocument();
  });

  it('has no accessibility violations, closed or open', async () => {
    const { container } = render(<PdfAttachment attachment={SAMPLE_PDF} />);
    await expectNoAxeViolations(container);

    render(<PdfAttachment attachment={SAMPLE_PDF} renderPage={() => <p>page</p>} defaultOpen />);
    await expectNoAxeViolations(document.body);
  });
});

describeThemeDensitySnapshots('PdfAttachment', () => <PdfAttachment attachment={SAMPLE_PDF} />);
