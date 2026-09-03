/**
 * A small JSON Schema checker for the one place the cockpit edits an object by hand.
 *
 * It covers the subset the daemon's generated schemas actually use — `$ref` into `$defs`,
 * `type`, `required`, `enum`, `anyOf`, `properties`, `items` — and it exists to catch a
 * typo before the round trip, not to decide anything. The daemon validates the same object
 * again and its refusal is what counts: no scientific rule lives here (principle P10).
 */
import type { Json, JsonObject } from './dto';

export interface SchemaIssue {
  path: string;
  message: string;
}

type Schema = Record<string, any>;

/** Every problem found, in document order; an empty list means "worth posting". */
export function validate(schema: Schema, value: unknown, root: Schema = schema): SchemaIssue[] {
  const issues: SchemaIssue[] = [];
  check(schema, value, '$', root, issues);
  return issues;
}

/** The sub-schema a `$ref` names, or `null` when it points outside this document. */
export function resolve(schema: Schema, root: Schema): Schema | null {
  const ref = schema.$ref;
  if (typeof ref !== 'string') return schema;
  const parts = ref.replace(/^#\//, '').split('/');
  let node: any = root;
  for (const part of parts) {
    if (node == null || typeof node !== 'object') return null;
    node = node[decodeURIComponent(part)];
  }
  return (node as Schema) ?? null;
}

function check(schema: Schema, value: unknown, path: string, root: Schema, issues: SchemaIssue[]) {
  const resolved = resolve(schema, root);
  if (!resolved) return;

  if (Array.isArray(resolved.anyOf)) {
    const branches = resolved.anyOf as Schema[];
    const matched = branches.some((branch) => validate(branch, value, root).length === 0);
    if (!matched) {
      issues.push({ path, message: `does not match any allowed shape` });
    }
    return;
  }

  if (Array.isArray(resolved.enum) && !resolved.enum.includes(value as Json)) {
    issues.push({ path, message: `must be one of: ${resolved.enum.join(', ')}` });
    return;
  }

  const kind = resolved.type;
  if (typeof kind === 'string' && !matchesType(kind, value)) {
    issues.push({ path, message: `must be ${kind}, got ${describe(value)}` });
    return;
  }

  if (kind === 'object' || (kind === undefined && isObject(value) && resolved.properties)) {
    const object = value as JsonObject;
    for (const name of (resolved.required ?? []) as string[]) {
      if (!(name in object)) issues.push({ path: `${path}.${name}`, message: 'is required' });
    }
    for (const [name, property] of Object.entries((resolved.properties ?? {}) as Schema)) {
      if (name in object) check(property, object[name], `${path}.${name}`, root, issues);
    }
    if (resolved.additionalProperties === false) {
      const allowed = new Set(Object.keys((resolved.properties ?? {}) as Schema));
      for (const name of Object.keys(object)) {
        if (!allowed.has(name)) issues.push({ path: `${path}.${name}`, message: 'is not allowed' });
      }
    }
    return;
  }

  if (kind === 'array' && Array.isArray(value) && resolved.items) {
    value.forEach((item, index) => check(resolved.items, item, `${path}[${index}]`, root, issues));
  }
}

function matchesType(kind: string, value: unknown): boolean {
  switch (kind) {
    case 'object':
      return isObject(value);
    case 'array':
      return Array.isArray(value);
    case 'string':
      return typeof value === 'string';
    case 'integer':
      return typeof value === 'number' && Number.isInteger(value);
    case 'number':
      return typeof value === 'number';
    case 'boolean':
      return typeof value === 'boolean';
    case 'null':
      return value === null;
    default:
      return true;
  }
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function describe(value: unknown): string {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  return typeof value;
}
