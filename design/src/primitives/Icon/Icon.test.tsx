import { render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { Icon } from './Icon';
import { ICON_NAMES, icons } from './icons';

describe('Icon', () => {
  it('renders the registered glyph at the requested size', () => {
    const { container } = render(<Icon name="search" size={24} />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('width', '24');
    expect(svg).toHaveAttribute('height', '24');
    expect(svg).toHaveAttribute('data-icon', 'search');
  });

  it('is hidden from assistive technology when it has no label', () => {
    const { container } = render(<Icon name="chevron-down" />);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('is announced as an image when it carries the meaning', () => {
    render(<Icon name="lock" label="Private" />);
    const img = screen.getByRole('img', { name: 'Private' });
    expect(img).not.toHaveAttribute('aria-hidden');
  });

  it('forwards a ref to the svg element', () => {
    const ref = createRef<SVGSVGElement>();
    render(<Icon name="check" ref={ref} />);
    expect(ref.current?.tagName.toLowerCase()).toBe('svg');
  });

  it('passes className and style through', () => {
    const { container } = render(<Icon name="check" className="custom" style={{ opacity: 0.5 }} />);
    const svg = container.querySelector('svg');
    expect(svg).toHaveClass('rh-icon', 'custom');
    expect(svg).toHaveStyle({ opacity: '0.5' });
  });

  it('registers every name the product depends on', () => {
    const required = [
      'chevron-down',
      'chevron-right',
      'x',
      'check',
      'search',
      'plus',
      'send',
      'square',
      'rotate-ccw',
      'paperclip',
      'image',
      'file-text',
      'file',
      'download',
      'zoom-in',
      'zoom-out',
      'external-link',
      'link',
      'alert-triangle',
      'alert-circle',
      'info',
      'circle-check',
      'circle-dashed',
      'lock',
      'eye-off',
      'clock',
      'history',
      'git-branch',
      'list',
      'table',
      'book-open',
      'pen-line',
      'sparkles',
      'panel-left',
      'panel-right',
      'menu',
      'more-horizontal',
      'copy',
      'trash-2',
      'settings',
      'sun',
      'moon',
      'folder',
      'folder-open',
      'play',
      'refresh-cw',
      'arrow-up',
      'arrow-down',
      'arrow-left',
      'arrow-right',
      'filter',
      'tag',
      'bookmark',
      'quote',
      'hash',
      'at-sign',
      'loader',
    ];
    for (const name of required) expect(ICON_NAMES).toContain(name);
  });

  it('maps every registry entry to a component', () => {
    for (const name of ICON_NAMES) expect(typeof icons[name]).not.toBe('undefined');
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <Icon name="sparkles" />
        <Icon name="lock" label="Private" />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('Icon', () => (
  <div>
    <Icon name="send" size={14} />
    <Icon name="send" size={16} />
    <Icon name="send" size={18} />
    <Icon name="send" size={20} />
    <Icon name="send" size={24} />
    <Icon name="circle-check" label="Accepted" />
  </div>
));
