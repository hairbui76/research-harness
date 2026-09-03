import { forwardRef } from 'react';
import { Badge } from '../../primitives/Badge';
import { Button } from '../../primitives/Button';
import { Icon } from '../../primitives/Icon';
import { Menu } from '../../primitives/Menu';
import { EGRESS_META } from '../../research/models';
import { cx } from '../../utils/cx';
import type { ModelOption } from '../models';

export interface ModelSelectorProps {
  options: readonly ModelOption[];
  /** Selected model id. */
  value: string;
  onChange: (option: ModelOption) => void;
  /** Accessible name for the control. Defaults to "Model". */
  label?: string;
  disabled?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}

/**
 * Which model the next message goes to.
 *
 * Every option states its provider, whether the request leaves the machine, and whether it
 * reads images — in text, not only as an icon, because "local or external" is a privacy
 * decision and not a decoration. Models that cannot serve the current draft stay in the
 * list with the reason attached rather than vanishing, so the researcher can see that a
 * vision model exists and why the current one will not do.
 */
export const ModelSelector = forwardRef<HTMLButtonElement, ModelSelectorProps>(
  function ModelSelector(
    { options, value, onChange, label = 'Model', disabled = false, size = 'sm', className },
    ref,
  ) {
    const selected = options.find((option) => option.id === value);
    const selectedEgress = selected ? EGRESS_META[selected.egressClass] : undefined;

    return (
      <Menu placement="top" align="start">
        <Menu.Trigger asChild>
          <Button
            ref={ref}
            className={cx('rh-model-selector__trigger', className)}
            variant="secondary"
            size={size}
            iconEnd="chevron-down"
            disabled={disabled}
            aria-label={`${label}: ${selected?.label ?? 'none selected'}`}
          >
            <span className="rh-model-selector__current">
              <span className="rh-model-selector__name">{selected?.label ?? 'Select a model'}</span>
              {selectedEgress ? (
                <span className="rh-model-selector__egress">
                  <Icon name={selectedEgress.icon} size={14} />
                  <span>{selectedEgress.label}</span>
                </span>
              ) : null}
            </span>
          </Button>
        </Menu.Trigger>
        <Menu.Content aria-label={label} className="rh-model-selector__menu">
          {options.map((option) => {
            const egress = EGRESS_META[option.egressClass];
            return (
              <Menu.Item
                key={option.id}
                disabled={!option.available}
                data-model={option.id}
                data-selected={option.id === value || undefined}
                icon={
                  <Icon name={option.id === value ? 'check' : 'circle-dashed'} size={16} />
                }
                onSelect={() => onChange(option)}
              >
                <span className="rh-model-selector__option">
                  <span className="rh-model-selector__option-head">
                    <span className="rh-model-selector__name">{option.label}</span>
                    <span className="rh-model-selector__provider">{option.provider}</span>
                  </span>
                  <span className="rh-model-selector__facts">
                    <Badge
                      tone={option.egressClass === 'external' ? 'warning' : 'neutral'}
                      icon={egress.icon}
                      size="sm"
                    >
                      {egress.label}
                    </Badge>
                    <Badge
                      tone="neutral"
                      icon={option.vision ? 'image' : 'eye-off'}
                      size="sm"
                    >
                      {option.vision ? 'Reads images' : 'Text only'}
                    </Badge>
                    <span className="rh-model-selector__context">
                      {option.contextTokens.toLocaleString('en-US')} tok context
                    </span>
                  </span>
                  {!option.available ? (
                    <span className="rh-model-selector__unavailable">
                      <Icon name="shield-off" size={14} />
                      <span>{option.unavailableReason ?? 'Not available here.'}</span>
                    </span>
                  ) : null}
                </span>
              </Menu.Item>
            );
          })}
        </Menu.Content>
      </Menu>
    );
  },
);
