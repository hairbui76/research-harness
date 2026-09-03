/**
 * The one place the local token is entered.
 *
 * Without it the daemon treats this window as an agent host, which is a correct and safe
 * state rather than an error — so the bar explains it and offers the fix instead of
 * blocking the cockpit (Product 29, 34).
 */
import { useState } from 'react';
import { useSession } from './session';

export function TokenBar() {
  const { canMutate, setToken, error, refresh, overview } = useSession();
  const [value, setValue] = useState('');

  if (canMutate && !error) return null;

  return (
    <div className="token-bar" role="region" aria-label="daemon connection">
      {error ? (
        <p className="error">
          The daemon did not answer ({error}). Start it with <code>research serve</code> and
          reload.
        </p>
      ) : (
        <p>
          Connected as <strong>{overview?.principal ?? 'unknown'}</strong>: this window may read
          and propose, and only the researcher accepts. Paste the token from{' '}
          <code>.research/daemon-token</code> to review.
        </p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setToken(value.trim() || null);
          setValue('');
          refresh();
        }}
      >
        <label htmlFor="daemon-token">Local token</label>
        <input
          id="daemon-token"
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          autoComplete="off"
        />
        <button type="submit">Connect</button>
      </form>
    </div>
  );
}
