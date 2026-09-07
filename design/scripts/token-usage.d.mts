/** Types for `token-usage.mjs`, so `tests/tokens.test.ts` can run the same census the lint does. */

export interface DeclaredToken {
  name: string;
  /** Repository-relative path of the file that declares it. */
  file: string;
  line: number;
}

export interface TokenCensus {
  declared: DeclaredToken[];
  /** Declared, and read by nothing outside its own declaration. */
  dead: DeclaredToken[];
  /** Dead and not explained by `HOST_TOKENS`: the set that fails the gate. */
  unexplained: DeclaredToken[];
}

/** Tokens allowed to have no consumer here, each mapped to the published set it belongs to. */
export declare const HOST_TOKENS: Readonly<Record<string, string>>;

export declare function tokenCensus(): TokenCensus;
