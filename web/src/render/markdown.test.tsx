/**
 * What a message may and may not do to the cockpit.
 *
 * A transcript is untrusted text: the model wrote it, or it came back from a provider that
 * read someone else's PDF. These tests pin the four properties the conversation route
 * rests on — mathematics renders with text for assistive technology, a broken expression
 * marks itself instead of taking the transcript down, raw HTML stays inert, and a
 * reference is handed to the app instead of navigating anywhere.
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Markdown, parseDeepLink, renderMarkdown } from './markdown';

function draw(text: string, options = {}) {
  return render(<>{renderMarkdown(text, options)}</>);
}

describe('Markdown', () => {
  it('renders Markdown structure and GFM tables inside a scrollable box', () => {
    const { container } = draw(
      [
        '## Findings',
        '',
        '| model | accuracy |',
        '| --- | --- |',
        '| baseline | 0.71 |',
        '',
        '- one',
        '- two',
      ].join('\n'),
    );

    expect(screen.getByRole('heading', { level: 2, name: 'Findings' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'accuracy' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'baseline' })).toBeInTheDocument();
    expect(container.querySelectorAll('li')).toHaveLength(2);

    // The table is in its own overflow box, reachable and scrollable from the keyboard.
    const box = screen.getByRole('region', { name: 'Table' });
    expect(box).toHaveClass('rh-md__table-scroll');
    expect(box).toHaveAttribute('tabindex', '0');
    expect(box.querySelector('table')).not.toBeNull();
  });

  it('renders inline maths with MathML beside the visual HTML', () => {
    const { container } = draw('The estimator is $\\hat{\\beta}_1$ throughout.');

    const katex = container.querySelector('.katex');
    expect(katex).not.toBeNull();

    // MathML is what a screen reader reads (conversation spec §9); the visual half is
    // hidden from it, and the annotation keeps the TeX the message actually contained.
    const mathml = container.querySelector('.katex-mathml');
    expect(mathml).not.toBeNull();
    expect(mathml?.querySelector('math')).not.toBeNull();
    expect(container.querySelector('.katex-mathml annotation')?.textContent).toBe(
      '\\hat{\\beta}_1',
    );
    expect(container.querySelector('.katex-html')).toHaveAttribute('aria-hidden', 'true');
    expect(container.querySelector('.katex-display')).toBeNull();
  });

  it('renders display maths as a display block', () => {
    const { container } = draw('$$\n\\sum_{i=1}^{n} x_i\n$$');

    expect(container.querySelector('.katex-display')).not.toBeNull();
    expect(container.querySelector('.katex-mathml annotation')?.textContent).toBe(
      '\\sum_{i=1}^{n} x_i',
    );
  });

  it('marks a broken expression instead of crashing, and keeps the rest of the message', () => {
    const { container } = draw('before $\\frac{$ after');

    const marker = screen.getByRole('img', {
      name: /Mathematics that could not be rendered: \\frac\{/,
    });
    expect(marker).toHaveClass('rh-md__math-error');
    // The failing source is the visible text, and it is on the node for a copy control.
    expect(marker).toHaveTextContent('\\frac{');
    expect(marker).toHaveAttribute('data-math-source', '\\frac{');
    // KaTeX's own inline colour is gone: the marker is inked by the theme's tokens.
    expect(marker.getAttribute('style')).toBeNull();
    expect(container.textContent).toContain('before');
    expect(container.textContent).toContain('after');
  });

  it('does not render raw HTML in a message', async () => {
    const alert = vi.fn();
    vi.stubGlobal('__markdownTestAlert', alert);
    const { container } = draw(
      '<script>globalThis.__markdownTestAlert()</script>\n\n<b>bold?</b>\n\nplain',
    );

    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('b')).toBeNull();
    expect(alert).not.toHaveBeenCalled();
    // react-markdown keeps the raw source as text, so nothing is silently swallowed.
    expect(container.textContent).toContain('<script>');
    expect(container.textContent).toContain('<b>bold?</b>');
    vi.unstubAllGlobals();
  });

  it('hands an rh:// link to onDeepLink instead of navigating', async () => {
    const onDeepLink = vi.fn();
    draw('see [the claim](rh://claim/C0041?message=M0042)', { onDeepLink });

    const link = screen.getByRole('link', { name: 'the claim' });
    expect(link).toHaveAttribute('href', 'rh://claim/C0041?message=M0042');
    expect(link).toHaveAttribute('data-deep-link-kind', 'claim');
    expect(link).not.toHaveAttribute('target');

    await userEvent.click(link);

    expect(onDeepLink).toHaveBeenCalledTimes(1);
    const link0 = onDeepLink.mock.calls[0]![0];
    expect(link0.kind).toBe('claim');
    expect(link0.id).toBe('C0041');
    expect(link0.params.get('message')).toBe('M0042');
  });

  it('opens an external link safely and drops a javascript: url', () => {
    draw('[docs](https://example.org/a) and [bad](javascript:alert(1))');

    const external = screen.getByRole('link', { name: 'docs' });
    expect(external).toHaveAttribute('target', '_blank');
    expect(external).toHaveAttribute('rel', 'noopener noreferrer');

    // `react-markdown`'s url sanitiser empties the href, and an empty href is not a link:
    // the text survives, and there is nothing to navigate to.
    expect(screen.getByText('bad').closest('a')).toBeNull();
    expect(screen.queryByRole('link', { name: 'bad' })).toBeNull();
  });

  it('renders a fenced code block with its language, and offers it to renderCode', () => {
    const { container } = draw('```python\nprint("hi")\n```');
    const code = container.querySelector('pre > code');
    expect(code).toHaveClass('language-python');
    expect(code?.textContent).toBe('print("hi")');

    const renderCode = vi.fn(({ code: source, language }) => (
      <div data-testid="slot" data-language={language}>
        {source}
      </div>
    ));
    render(<Markdown text={'```python\nprint("hi")\n```'} renderCode={renderCode} />);
    expect(renderCode).toHaveBeenCalledWith({ code: 'print("hi")', language: 'python' });
    expect(screen.getByTestId('slot')).toHaveAttribute('data-language', 'python');
  });

  it('does not fetch a remote image unless the caller allows it', () => {
    const { container } = draw('![a figure](https://tracker.example/pixel.png)');
    expect(container.querySelector('img')).toBeNull();
    const link = screen.getByRole('link', { name: /a figure/ });
    expect(link).toHaveAttribute('href', 'https://tracker.example/pixel.png');

    const allowed = render(
      <Markdown text="![a figure](https://tracker.example/pixel.png)" allowRemoteImages />,
    );
    expect(allowed.container.querySelector('img')).toHaveAttribute('alt', 'a figure');
  });
});

describe('parseDeepLink', () => {
  it('reads every deep-link shape the plan names, and nothing else', () => {
    expect(parseDeepLink('rh://evidence/E0482')).toMatchObject({ kind: 'evidence', id: 'E0482' });
    expect(parseDeepLink('rh://session/CS0001?message=M0042')?.params.get('message')).toBe('M0042');
    expect(parseDeepLink('rh://manuscript/main.tex?line=120')).toMatchObject({
      kind: 'manuscript',
      id: 'main.tex',
    });
    const artifact = parseDeepLink('rh://artifact/A0017-3?page=6&block=B0081');
    expect(artifact?.id).toBe('A0017-3');
    expect(artifact?.params.get('page')).toBe('6');

    expect(parseDeepLink('https://example.org')).toBeNull();
    expect(parseDeepLink('rh://claim')).toBeNull();
    expect(parseDeepLink('javascript:alert(1)')).toBeNull();
  });
});
