import { forwardRef, useState } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { Badge } from '../../primitives/Badge';
import { Button } from '../../primitives/Button';
import { Dialog } from '../../primitives/Dialog';
import { Radio, RadioGroup } from '../../primitives/Radio';
import { ErrorNotice } from '../../states/ErrorNotice';
import { cx } from '../../utils/cx';
import { EntityRef } from '../EntityRef';
import type { EntityRefModel, IdentityChoice, SaveToCorpusState } from '../models';

export interface SaveToCorpusCorpusLinks {
  work?: EntityRefModel;
  version?: EntityRefModel;
  artifact?: EntityRefModel;
}

export interface SaveToCorpusActionProps
  extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'onSelect'> {
  state: SaveToCorpusState;
  /**
   * The identities the host resolved for these bytes. They are rendered in the order given
   * and nothing here ranks, merges or invents one: duplicate detection and Work/Version
   * matching are corpus rules, and they live in the daemon.
   */
  choices?: readonly IdentityChoice[];
  /** File name, used in the dialog title and in the failure notice. */
  name?: string;
  /** Where the bytes ended up once `in_corpus`. */
  corpus?: SaveToCorpusCorpusLinks;
  /** Failure text from the host, shown with the retry. */
  error?: string;
  /** Begin identity resolution. */
  onStart?: () => void;
  /** Confirm the chosen identity. */
  onConfirm: (choice: IdentityChoice) => void;
  onRetry?: () => void;
  onCancel?: () => void;
  onOpenRef?: (entity: EntityRefModel) => void;
  /** Button label while idle. */
  label?: ReactNode;
  size?: 'sm' | 'md';
}

const CHOICE_KIND_LABEL: Record<IdentityChoice['kind'], string> = {
  existing_artifact: 'Existing artifact',
  existing_work_new_version: 'New version of an existing work',
  new_work: 'New work',
};

/**
 * `Save to corpus`, as a button and a confirmation dialog.
 *
 * Attachments are session working material; this is the one explicit step that gives bytes
 * a corpus identity. The component owns none of that: it shows the identities the host
 * resolved, reports the one the researcher confirmed, and stays out of the way. It cannot
 * merge works, detect duplicates or accept evidence — saving to the corpus creates or links
 * identity and nothing else.
 *
 * A failure leaves the session attachment visibly intact and offers a retry, because the
 * researcher's file is not the thing that failed.
 */
export const SaveToCorpusAction = forwardRef<HTMLDivElement, SaveToCorpusActionProps>(
  function SaveToCorpusAction(
    {
      state,
      choices,
      name,
      corpus,
      error,
      onStart,
      onConfirm,
      onRetry,
      onCancel,
      onOpenRef,
      label = 'Save to corpus',
      size = 'sm',
      className,
      ...rest
    },
    ref,
  ) {
    // Nothing is preselected: choosing an identity is the researcher's decision, and a
    // default answer in this dialog would be this component making it for them.
    const [selected, setSelected] = useState<string | null>(null);
    const list = choices ?? [];
    const chosen = selected === null ? undefined : list[Number(selected)];

    const subject = name ?? 'this file';

    return (
      <div
        ref={ref}
        className={cx('rh-save-to-corpus', className)}
        data-state={state}
        {...rest}
      >
        {state === 'in_corpus' ? (
          <div className="rh-save-to-corpus__result">
            <Badge tone="success" icon="library" size="sm">
              In corpus
            </Badge>
            {corpus?.work ? <EntityRef entity={corpus.work} onOpen={onOpenRef} size="sm" /> : null}
            {corpus?.version ? (
              <EntityRef entity={corpus.version} onOpen={onOpenRef} size="sm" />
            ) : null}
            {corpus?.artifact ? (
              <EntityRef entity={corpus.artifact} onOpen={onOpenRef} size="sm" />
            ) : null}
          </div>
        ) : (
          <Button
            size={size}
            variant="secondary"
            iconStart="library"
            loading={state === 'resolving' || state === 'promoting'}
            loadingLabel={state === 'resolving' ? 'Checking the corpus' : 'Saving to the corpus'}
            disabled={state === 'choose_identity'}
            onClick={onStart}
          >
            {label}
          </Button>
        )}

        {state === 'failed' ? (
          <ErrorNotice
            className="rh-save-to-corpus__error"
            kind="retryable"
            title={`${subject} was not saved to the corpus`}
            description={error}
            safety={{
              source: 'safe',
              note: `The session copy of ${subject} is unchanged and can be sent, previewed and saved again.`,
            }}
            actions={[
              ...(onRetry ? [{ label: 'Try again', onClick: onRetry, iconStart: 'refresh-cw' as const }] : []),
              ...(onCancel ? [{ label: 'Not now', onClick: onCancel, variant: 'ghost' as const }] : []),
            ]}
          />
        ) : null}

        <Dialog
          open={state === 'choose_identity'}
          size="md"
          onOpenChange={(open) => {
            if (!open) onCancel?.();
          }}
        >
          <Dialog.Header>Save {subject} to the corpus</Dialog.Header>
          <Dialog.Body>
            <p className="rh-save-to-corpus__lead">
              Choose the identity these bytes belong to. Saving copies the file into canonical
              corpus storage and runs the normal parsing workflow. It does not create evidence
              or accept anything: extraction still goes through candidate, verification and
              review.
            </p>
            {list.length === 0 ? (
              <p className="rh-save-to-corpus__empty">
                The host resolved no identity for {subject}. Cancel and try again once the
                corpus index is available.
              </p>
            ) : (
              <RadioGroup label="Corpus identity" value={selected} onValueChange={setSelected}>
                {list.map((choice, index) => (
                  <Radio
                    key={`${choice.kind}-${index}`}
                    value={String(index)}
                    label={
                      <span className="rh-save-to-corpus__choice">
                        <span className="rh-save-to-corpus__choice-label">{choice.label}</span>
                        <span className="rh-text-label">{CHOICE_KIND_LABEL[choice.kind]}</span>
                      </span>
                    }
                    description={
                      <>
                        {choice.detail}
                        {/* Ids read as text here rather than as links: a radio's description
                            is not a place to put another tab stop. */}
                        <span className="rh-save-to-corpus__choice-refs">
                          {[choice.work, choice.version, choice.artifact]
                            .filter((entity): entity is EntityRefModel => entity !== undefined)
                            .map((entity) => (
                              <span key={entity.id} className="rh-save-to-corpus__choice-ref">
                                {entity.id}
                              </span>
                            ))}
                        </span>
                      </>
                    }
                  />
                ))}
              </RadioGroup>
            )}
          </Dialog.Body>
          <Dialog.Footer>
            <Button variant="secondary" onClick={onCancel}>
              Cancel
            </Button>
            {/* Not "Save to corpus" again: the trigger behind the dialog already carries
                that name, and two controls with one name is a maze from the keyboard. */}
            <Button
              variant="primary"
              disabled={chosen === undefined}
              onClick={() => {
                if (chosen !== undefined) onConfirm(chosen);
              }}
            >
              Confirm and save
            </Button>
          </Dialog.Footer>
        </Dialog>
      </div>
    );
  },
);
