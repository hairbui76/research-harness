/**
 * The Edit action's editor: the Evidence object as JSON, checked against the daemon's own
 * schema before it is posted.
 *
 * The check is a courtesy — it catches a typo without a round trip. The daemon validates
 * the same object again, and an edit that moves the source anchor is refused there, not
 * here: the rule lives in `review.edit`, never in this component.
 */
import { useMemo, useState } from 'react';
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

export function JsonEditor({ value, onSubmit, onCancel, busy, disabled, submitLabel }: JsonEditorProps) {
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
    <div className="json-editor">
      <label htmlFor="evidence-json">Evidence (JSON)</label>
      <textarea
        id="evidence-json"
        spellCheck={false}
        rows={18}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      {parseError ? <p className="error" role="alert">{parseError}</p> : null}
      {issues.length > 0 ? (
        <ul className="error" role="alert">
          {issues.map((issue) => (
            <li key={`${issue.path}:${issue.message}`}>
              <code>{issue.path}</code> {issue.message}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="actions">
        <button type="button" onClick={submit} disabled={disabled || busy}>
          {submitLabel ?? 'Accept the edit'}
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  );
}
