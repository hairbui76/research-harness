/**
 * Opening a session: the one decision that cannot be taken back.
 *
 * A session's visibility is fixed when it is created — there is no capability that changes
 * it afterwards — and it decides what the session may later be bound to: `private` never
 * leaves the machine unless policy allows it, so a runtime or an entry that would send it
 * to a vendor is refused, while `project` may reach the selected provider under the egress
 * policy. A rail button that created a private session in silence made that choice on the
 * researcher's behalf and closed off the composer's binding for good, which is why the
 * click now asks.
 *
 * The default is not restated: leaving the choice alone sends no `visibility` at all, so
 * the daemon applies its own default rather than the browser asserting one. Both words in
 * the list are the daemon's, and they are the same two the session rail already shows.
 */
import { useState } from 'react';
import { Button, Dialog, Select } from '@research-harness/design';
import type { SessionVisibility } from '../../api/dto';

/** The empty value means "say nothing", which is how the daemon's default stays the default. */
const DAEMON_DEFAULT = '';

export interface NewSessionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Creates the session. `visibility` is absent when the researcher left the default. */
  onCreate: (visibility?: SessionVisibility) => void;
}

export function NewSessionDialog({ open, onOpenChange, onCreate }: NewSessionDialogProps) {
  const [visibility, setVisibility] = useState<string>(DAEMON_DEFAULT);

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="sm">
      <Dialog.Header>New session</Dialog.Header>
      <Dialog.Body>
        <Select
          label="Visibility"
          value={visibility}
          description={
            'Only a project session can be bound to an external runtime or entry, and ' +
            'visibility cannot be changed once the session exists.'
          }
          onChange={(event) => setVisibility(event.target.value)}
        >
          <option value={DAEMON_DEFAULT}>Private (default)</option>
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
            onCreate(visibility === DAEMON_DEFAULT ? undefined : (visibility as SessionVisibility));
            onOpenChange(false);
          }}
        >
          Create session
        </Button>
      </Dialog.Footer>
    </Dialog>
  );
}
