import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { expectNoAxeViolations } from '../../../tests/axe';
import { describeThemeDensitySnapshots } from '../../../tests/variants';
import { RESOLUTION_META } from '../models';
import {
  SAMPLE_BROKEN_REF,
  SAMPLE_CLAIM_REF,
  SAMPLE_PRIVATE_REF,
  SAMPLE_STALE_REF,
  SAMPLE_UNRESOLVED_REF,
  SAMPLE_WORK,
} from '../samples';
import { EntityRef } from './EntityRef';

describe('EntityRef', () => {
  it('shows the id, the label and the authority', () => {
    const { container } = render(<EntityRef entity={SAMPLE_WORK} describe={false} />);
    expect(screen.getByText('W0017')).toBeInTheDocument();
    expect(screen.getByText(SAMPLE_WORK.label as string)).toBeInTheDocument();
    expect(container.querySelector('.rh-entity-ref__authority')).toHaveTextContent('Accepted');
  });

  it.each([SAMPLE_STALE_REF, SAMPLE_PRIVATE_REF, SAMPLE_UNRESOLVED_REF, SAMPLE_BROKEN_REF])(
    'writes the resolution state out in words ($resolution)',
    (entity) => {
      const { container } = render(<EntityRef entity={entity} describe={false} />);
      const chip = container.querySelector('.rh-entity-ref');
      expect(chip).toHaveAttribute('data-resolution', entity.resolution);
      expect(chip).toHaveTextContent(RESOLUTION_META[entity.resolution].label);
    },
  );

  it('says nothing extra when the reference resolved', () => {
    const { container } = render(<EntityRef entity={SAMPLE_CLAIM_REF} describe={false} />);
    expect(container.querySelector('.rh-entity-ref__resolution')).toBeNull();
  });

  it('renders a link when the model carries a deep link, and a button otherwise', () => {
    const { container: withHref } = render(<EntityRef entity={SAMPLE_WORK} describe={false} />);
    expect(withHref.querySelector('a')).toHaveAttribute('href', 'rh://work/W0017');

    const { container: withoutHref } = render(
      <EntityRef entity={SAMPLE_CLAIM_REF} onOpen={() => undefined} describe={false} />,
    );
    expect(withoutHref.querySelector('button')).not.toBeNull();
  });

  it('is static text when there is neither a link nor a handler', () => {
    const { container } = render(<EntityRef entity={SAMPLE_CLAIM_REF} />);
    expect(container.querySelector('button')).toBeNull();
    expect(container.querySelector('a')).toBeNull();
  });

  it('opens from the keyboard and suppresses the link navigation', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<EntityRef entity={SAMPLE_WORK} onOpen={onOpen} describe={false} />);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onOpen).toHaveBeenCalledWith(SAMPLE_WORK);
  });

  it('describes the kind and the resolution on focus', async () => {
    const user = userEvent.setup();
    render(<EntityRef entity={SAMPLE_STALE_REF} onOpen={() => undefined} />);
    await user.tab();
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      RESOLUTION_META.stale.description,
    );
  });

  it('has no accessibility violations', async () => {
    const { container } = render(
      <div>
        <EntityRef entity={SAMPLE_WORK} onOpen={() => undefined} describe={false} />
        <EntityRef entity={SAMPLE_STALE_REF} onOpen={() => undefined} describe={false} />
        <EntityRef entity={SAMPLE_BROKEN_REF} describe={false} />
      </div>,
    );
    await expectNoAxeViolations(container);
  });
});

describeThemeDensitySnapshots('EntityRef', () => (
  <div>
    <EntityRef entity={SAMPLE_WORK} describe={false} />
    <EntityRef entity={SAMPLE_STALE_REF} describe={false} />
    <EntityRef entity={SAMPLE_PRIVATE_REF} describe={false} />
    <EntityRef entity={SAMPLE_BROKEN_REF} describe={false} size="sm" />
  </div>
));
