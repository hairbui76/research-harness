/**
 * Opening a session: the one decision that cannot be taken back.
 *
 * A session's visibility is fixed when it is created — there is no capability that changes
 * it afterwards — and it decides what the session may later be bound to. A `private`
 * session is refused a CLI runtime binding outright, at bind time; an entry binding is
 * stored, and refused at send time if that entry is external. Either way a private session
 * never reaches an external model, which is the whole point of it. A rail button that
 * created a private session in silence made that choice on the researcher's behalf and
 * closed off the composer's binding for good, which is why the click now asks.
 *
 * The default is not restated on the wire: choosing `private` — the value the dialog opens
 * on — sends no `visibility` at all, so the daemon applies its own default rather than the
 * browser asserting one. Both option values are the daemon's own words, so nothing here
 * encodes a third state that would have to be translated somewhere else.
 */
import { useEffect, useRef, useState } from 'react';
import { Button, Dialog, Select } from '@research-harness/design';
import type { SessionVisibility } from '../../api/dto';

/** The two words the daemon uses, and the one the session rail already shows as a badge. */
const DEFAULT_VISIBILITY: SessionVisibility = 'private';

export interface NewSessionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Creates the session. `visibility` is absent when the researcher left the default. */
  onCreate: (visibility?: SessionVisibility) => void;
}

export function NewSessionDialog({ open, onOpenChange, onCreate }: NewSessionDialogProps) {
  const [visibility, setVisibility] = useState<SessionVisibility>(DEFAULT_VISIBILITY);
  const choice = useRef<HTMLSelectElement>(null);

  /**
   * Each opening is its own question.
   *
   * The dialog stays mounted between openings, so without this a choice abandoned on the
   * way out would be waiting, already made, the next time — and this is the one choice that
   * cannot be corrected after the fact.
   */
  useEffect(() => {
    if (!open) return;
    setVisibility(DEFAULT_VISIBILITY);
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="sm" initialFocusRef={choice}>
      <Dialog.Header>New session</Dialog.Header>
      <Dialog.Body>
        <Select
          ref={choice}
          label="Visibility"
          value={visibility}
          description={
            'Only a project session can be bound to a CLI runtime; a private session never ' +
            'sends to an external model, and visibility cannot be changed once the session ' +
            'exists.'
          }
          onChange={(event) => setVisibility(event.target.value as SessionVisibility)}
        >
          <option value="private">Private (default)</option>
          <option value="project">Project</option>
        </Select>
      </Dialog.Body>
      <Dialog.Footer>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={() => {
            // The daemon's default is the daemon's to apply: the usual session is still the
            // request that says nothing about visibility.
            onCreate(visibility === DEFAULT_VISIBILITY ? undefined : visibility);
            onOpenChange(false);
          }}
        >
          Create session
        </Button>
      </Dialog.Footer>
    </Dialog>
  );
}
