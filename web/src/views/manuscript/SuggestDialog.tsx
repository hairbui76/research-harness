/**
 * Asking a model to rewrite one span of the manuscript.
 *
 * The dialog collects what `manuscript.suggest` needs and nothing else: the file, the line
 * range the cursor or the selection named, a style pass or a free instruction, and the
 * provider `research.yaml` configures. It starts nothing on its own and it never writes
 * source — the capability stages a candidate under `.research/staging` and the manuscript
 * file stays byte-identical until somebody applies the diff (LaTeX spec §4).
 *
 * The provider is a text field rather than a list because no read in this build reports the
 * configured provider names; the daemon refuses an unknown one and its refusal is shown
 * here. The last one used is remembered per browser, which is a convenience, not a default.
 */
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Button, Dialog, DialogBody, DialogFooter, DialogHeader, Input, Select, Textarea } from '@research-harness/design';
import type { SuggestionRequest } from '../../api/dto';
import { ErrorBox } from '../../components/Feedback';

/** The style passes `manuscript.suggest` offers, and the free-instruction escape. */
const STYLES = [
  { value: 'humanize', label: 'Humanize — plain academic prose, same claims' },
  { value: 'venue', label: 'Venue — house style, sentence length and voice' },
  { value: 'copyedit', label: 'Copy-edit — grammar and punctuation only' },
  { value: 'instruction', label: 'A free instruction of my own' },
] as const;

const PROVIDER_KEY = 'rh.manuscript.suggest.provider';

export interface SuggestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  file: string;
  /** The line range the editor's cursor or selection named. */
  lineStart: number;
  lineEnd: number;
  suggesting: boolean;
  error: string | null;
  onSubmit: (request: SuggestionRequest) => void;
}

function readProvider(): string {
  try {
    return window.localStorage.getItem(PROVIDER_KEY) ?? '';
  } catch {
    return '';
  }
}

function rememberProvider(provider: string): void {
  try {
    window.localStorage.setItem(PROVIDER_KEY, provider);
  } catch {
    // A browser that refuses storage still gets to ask for a suggestion.
  }
}

export function SuggestDialog({
  open,
  onOpenChange,
  file,
  lineStart,
  lineEnd,
  suggesting,
  error,
  onSubmit,
}: SuggestDialogProps) {
  const [style, setStyle] = useState<string>('humanize');
  const [instruction, setInstruction] = useState('');
  const [provider, setProvider] = useState('');
  const [start, setStart] = useState(lineStart);
  const [end, setEnd] = useState(lineEnd);
  const [invalid, setInvalid] = useState<string | null>(null);

  // The range comes from wherever the cursor was when the dialog was opened.
  useEffect(() => {
    if (!open) return;
    setStart(lineStart);
    setEnd(lineEnd);
    setProvider((current) => current || readProvider());
    setInvalid(null);
  }, [lineEnd, lineStart, open]);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const named = provider.trim();
    if (!named) {
      setInvalid('Name the provider to ask; research.yaml’s `providers:` list has the names.');
      return;
    }
    if (style === 'instruction' && !instruction.trim()) {
      setInvalid('Write the instruction, or choose one of the style passes above.');
      return;
    }
    if (start < 1 || end < start) {
      setInvalid('The last line has to be the first line or later.');
      return;
    }
    setInvalid(null);
    rememberProvider(named);
    onSubmit({
      file,
      line_start: start,
      line_end: end,
      provider: named,
      ...(style === 'instruction' ? {} : { style }),
      ...(instruction.trim() ? { instruction: instruction.trim() } : {}),
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="md">
      <DialogHeader>Suggest an edit</DialogHeader>
      <DialogBody>
        <form id="rh-suggest-form" className="rh-web-stack rh-web-stack--tight" onSubmit={submit}>
          <p className="rh-text-secondary">
            {`Lines ${start}–${end} of ${file} are sent to the model with the accepted state
            they are anchored to. The answer comes back as a diff to review: nothing is
            written to the file until you apply it.`}
          </p>
          <div className="rh-web-row">
            <Input
              label="First line"
              type="number"
              min={1}
              value={start}
              onChange={(event) => setStart(Number(event.target.value))}
            />
            <Input
              label="Last line"
              type="number"
              min={1}
              value={end}
              onChange={(event) => setEnd(Number(event.target.value))}
            />
          </div>
          <Select
            label="Style pass"
            description="Every pass keeps citations, equations, numbers, units and quotations verbatim."
            value={style}
            onChange={(event) => setStyle(event.target.value)}
          >
            {STYLES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
          <Textarea
            label="Instruction"
            description={
              style === 'instruction'
                ? 'What to change. A rewrite that changes a proposition is refused, whatever this says.'
                : 'Optional: anything the style pass should know about this passage.'
            }
            rows={3}
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
          />
          <Input
            label="Provider"
            description="A name from the `providers:` list in research.yaml."
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          />
          {invalid ? (
            <p className="rh-text-secondary" role="alert">
              {invalid}
            </p>
          ) : null}
          {error ? <ErrorBox error={error} /> : null}
        </form>
      </DialogBody>
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
          Cancel
        </Button>
        <Button type="submit" form="rh-suggest-form" variant="primary" loading={suggesting}>
          Ask for a candidate
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
