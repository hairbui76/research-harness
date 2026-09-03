/**
 * The one place the local token is entered.
 *
 * Without it the daemon treats this window as an agent host, which is a correct and safe
 * state rather than an error — so the bar explains it and offers the fix instead of
 * blocking the cockpit (PRODUCT §29, §34).
 *
 * Composed from the Design System: `ErrorNotice` states what happened and whether
 * anything is at risk, and the field and the button are the package's `Input` and
 * `Button`. The bar owns no styling of its own beyond where it sits.
 */
import { useState } from 'react';
import { Button, ErrorNotice, Input } from '@research-harness/design';
import { useSession } from './session';

export function TokenBar() {
  const { canMutate, setToken, error, refresh, overview } = useSession();
  const [value, setValue] = useState('');

  if (canMutate && !error) return null;

  const form = (
    <form
      className="rh-web-token-form"
      onSubmit={(event) => {
        event.preventDefault();
        setToken(value.trim() || null);
        setValue('');
        refresh();
      }}
    >
      <Input
        id="daemon-token"
        label="Local token"
        type="password"
        autoComplete="off"
        fieldClassName="rh-web-token-field"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <Button type="submit" variant="primary" size="sm">
        Connect
      </Button>
    </form>
  );

  return (
    <div className="rh-web-token-bar">
      {error ? (
        <ErrorNotice
          kind="retryable"
          title="The daemon did not answer"
          description={
            <>
              Start it with <code>research serve</code> and reload, or paste the local token
              below.
            </>
          }
          detail={error}
          safety={{ source: 'safe', note: 'Nothing was written; this window only reads.' }}
          actions={[{ label: 'Try again', onClick: refresh, iconStart: 'refresh-cw' }]}
        >
          {form}
        </ErrorNotice>
      ) : (
        <ErrorNotice
          kind="blocked"
          title={`Connected as ${overview?.principal ?? 'unknown'}`}
          description={
            <>
              This window may read and propose, and only the researcher accepts. Paste the
              token from <code>.research/daemon-token</code> to review.
            </>
          }
          safety={{ draft: 'safe', source: 'safe' }}
        >
          {form}
        </ErrorNotice>
      )}
    </div>
  );
}
