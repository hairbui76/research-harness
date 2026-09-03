/**
 * The Edit action's editor: the Evidence object as JSON, checked against the daemon's own
 * schema before it is posted.
 *
 * The check is a courtesy — it catches a typo without a round trip. The daemon validates
 * the same object again, and an edit that moves the source anchor is refused there, not
 * here: the rule lives in `review.edit`, never in this component.
 */
import { useMemo, useState } from 'react';
import { Button, ErrorNotice, Textarea } from '@research-harness/design';
import { EDIT_CANDIDATE_PROPERTY, EDIT_CANDIDATE_SCHEMA } from '../api/capabilities.gen';
import type { Json } from '../api/dto';
import { resolve, validate } from '../api/schema';
import type { SchemaIssue } from '../api/schema';

const SCHEMA = EDIT_CANDIDATE_SCHEMA as unknown as Record<string, any>;

/** The `Evidence` sub-schema of the `review.edit` request, for a hand edit. */
export function evidenceSchema(): Record<string, any> | null {
  const property = SCHEMA.properties?.[EDIT_CANDIDATE_PROPERTY];
  return property ? resolve(property, SCHEMA) : null;
}

export interface JsonEditorProps {
  value: Json;
  onSubmit: (edited: Json) => void;
  onCancel: () => void;
  busy?: boolean;
  disabled?: boolean;
  submitLabel?: string;
}

export function JsonEditor({
  value,
  onSubmit,
  onCancel,
  busy,
  disabled,
  submitLabel,
}: JsonEditorProps) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [issues, setIssues] = useState<SchemaIssue[]>([]);
  const [parseError, setParseError] = useState<string | null>(null);
  const schema = useMemo(() => evidenceSchema(), []);

  function submit() {
    let parsed: Json;
    try {
      parsed = JSON.parse(text) as Json;
    } catch (cause) {
      setParseError(cause instanceof Error ? cause.message : String(cause));
      return;
    }
    setParseError(null);
    const found = schema ? validate(schema, parsed, SCHEMA) : [];
    setIssues(found);
    if (found.length === 0) onSubmit(parsed);
  }

  return (
    <div className="rh-web-stack rh-web-stack--tight">
      <Textarea
        id="evidence-json"
        label="Evidence (JSON)"
        className="rh-web-json"
        spellCheck={false}
        rows={18}
        value={text}
        onChange={(event) => setText(event.target.value)}
        {...(parseError ? { error: parseError } : {})}
      />
      {issues.length > 0 ? (
        <ErrorNotice
          kind="blocked"
          title="The edit does not match the daemon's schema"
          description="Fix these and the edit can be posted; the daemon checks the object again."
          safety={{ draft: 'safe' }}
        >
          <ul>
            {issues.map((issue) => (
              <li key={`${issue.path}:${issue.message}`}>
                <code>{issue.path}</code> {issue.message}
              </li>
            ))}
          </ul>
        </ErrorNotice>
      ) : null}
      <div className="rh-web-row">
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={submit}
          disabled={disabled || busy}
          loading={busy === true}
        >
          {submitLabel ?? 'Accept the edit'}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
