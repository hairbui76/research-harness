/**
 * Where the local token comes from, and where it is kept.
 *
 * The daemon's authority is a file under `.research/` that only a local process can read
 * (Product 34). The cockpit gets it one of two ways: the researcher opens the URL the
 * `research serve` banner prints, which carries `?token=`, or they paste it once. Either
 * way it is stored in `localStorage` for this origin and stripped from the address bar, so
 * it does not end up in a bookmark or a screenshot.
 *
 * Without a token the cockpit is an `agent_host`: it reads everything and accepts nothing.
 */
const STORAGE_KEY = 'research-harness.token';

/** The token for this session: the query parameter wins, then whatever was stored. */
export function readToken(location: Location = window.location): string | null {
  const url = new URL(location.href);
  const fromQuery = url.searchParams.get('token');
  if (fromQuery) {
    storeToken(fromQuery);
    url.searchParams.delete('token');
    window.history?.replaceState?.({}, '', `${url.pathname}${url.search}${url.hash}`);
    return fromQuery;
  }
  return storedToken();
}

export function storedToken(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(STORAGE_KEY, token);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* a browser with storage disabled still reads; it just cannot remember the token */
  }
}
