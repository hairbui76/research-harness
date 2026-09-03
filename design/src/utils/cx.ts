/** Class-name joiner. No dependency, no dynamic class generation — just filtering. */

export type ClassValue =
  | string
  | number
  | false
  | null
  | undefined
  | ClassValue[]
  | { [key: string]: boolean | null | undefined };

/** Join truthy class values into one `className` string. */
export function cx(...values: ClassValue[]): string {
  const out: string[] = [];
  for (const value of values) {
    if (!value && value !== 0) continue;
    if (typeof value === 'string' || typeof value === 'number') {
      out.push(String(value));
    } else if (Array.isArray(value)) {
      const nested = cx(...value);
      if (nested) out.push(nested);
    } else {
      for (const [key, enabled] of Object.entries(value)) {
        if (enabled) out.push(key);
      }
    }
  }
  return out.join(' ');
}
