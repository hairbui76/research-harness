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

/**
 * The multi-project app's token, and the one-time value that fetches it.
 *
 * The workspace token above belongs to one `.research/` directory and is remembered for
 * this origin. The application token is different in both respects (design §8.1): it is
 * the whole app's authority, so it lives in `sessionStorage` and dies with the tab, and it
 * never travels in a URL. What travels is a single-use bootstrap nonce, exchanged once at
 * `/api/app/session` and then worthless — so it is stripped from the address bar and never
 * written anywhere.
 */
const APP_STORAGE_KEY = 'research-harness.app-token';

/**
 * The launch nonce, read once and removed from the URL.
 *
 * Returns null when the page was not opened from the `research app` banner: the caller
 * then falls back to whatever this browser session already holds.
 */
export function readBootstrap(location: Location = window.location): string | null {
  const url = new URL(location.href);
  const bootstrap = url.searchParams.get('bootstrap');
  if (!bootstrap) return null;
  url.searchParams.delete('bootstrap');
  window.history?.replaceState?.({}, '', `${url.pathname}${url.search}${url.hash}`);
  return bootstrap;
}

export function storedAppToken(): string | null {
  try {
    return window.sessionStorage.getItem(APP_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeAppToken(token: string | null): void {
  try {
    if (token) window.sessionStorage.setItem(APP_STORAGE_KEY, token);
    else window.sessionStorage.removeItem(APP_STORAGE_KEY);
  } catch {
    /* storage disabled: the tab still works, it just cannot survive a reload */
  }
}
