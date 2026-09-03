/**
 * The Edit action's local check: enough to catch a typo before the round trip, and no more.
 *
 * The schema is the daemon's own, generated from `review.edit` — the request the Edit
 * action actually posts. What is asserted here is that the checker follows a `$ref` into
 * `$defs` and reports the missing field by path — the two things that make the message
 * useful. Whether the edit is *allowed* is the daemon's judgement and is not modelled here.
 */
import { describe, expect, it } from 'vitest';
import { EDIT_CANDIDATE_PROPERTY, EDIT_CANDIDATE_SCHEMA } from './capabilities.gen';
import { resolve, validate } from './schema';
import { evidenceSchema } from '../components/JsonEditor';
import candidate from '../test/fixtures/candidate.json';

const SCHEMA = EDIT_CANDIDATE_SCHEMA as unknown as Record<string, any>;

describe('the generated Evidence schema', () => {
  it('is reachable through the `edited` property of the review request', () => {
    expect(EDIT_CANDIDATE_PROPERTY).toBe('edited');
    expect(Object.keys(SCHEMA.properties)).toEqual(['candidate_id', 'edited']);
    const evidence = evidenceSchema();
    expect(evidence).not.toBeNull();
    expect(evidence?.properties).toHaveProperty('source');
    expect(evidence?.properties).toHaveProperty('content');
  });

  it('resolves a `$ref` into `$defs`', () => {
    const resolved = resolve({ $ref: '#/$defs/Evidence' }, SCHEMA);
    expect(resolved?.title).toBe('Evidence');
  });
});

describe('validating a hand edit', () => {
  it('accepts the candidate the daemon just handed us', () => {
    const evidence = evidenceSchema();
    expect(validate(evidence!, candidate.evidence, SCHEMA)).toEqual([]);
  });

  it('names the missing field by path', () => {
    const evidence = evidenceSchema();
    const broken = { ...(candidate.evidence as Record<string, unknown>) };
    delete broken.source;

    const issues = validate(evidence!, broken, SCHEMA);

    expect(issues).toContainEqual({ path: '$.source', message: 'is required' });
  });

  it('reports a field of the wrong type rather than posting it', () => {
    const evidence = evidenceSchema();
    const broken = { ...(candidate.evidence as Record<string, unknown>), origin: 42 };

    const issues = validate(evidence!, broken, SCHEMA);

    expect(issues.map((issue) => issue.path)).toContain('$.origin');
  });

  it('refuses a key the closed model on the daemon would reject', () => {
    const evidence = evidenceSchema();
    const broken = { ...(candidate.evidence as Record<string, unknown>), invented: true };

    const issues = validate(evidence!, broken, SCHEMA);

    expect(issues).toContainEqual({ path: '$.invented', message: 'is not allowed' });
  });
});
