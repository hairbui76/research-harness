/** The three states every read has, rendered the same way everywhere. */
import type { ReactNode } from 'react';

export function Loading({ what }: { what: string }) {
  return (
    <p className="muted" role="status">
      Reading {what}…
    </p>
  );
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div className="error" role="alert">
      <p>{error}</p>
      {retry ? (
        <button type="button" onClick={retry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted empty">{children}</p>;
}

export function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <header className="panel-head">
        <h2>{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

/** A definition row: the label the daemon uses, and the value it reported. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <span className="field-value">{children}</span>
    </div>
  );
}

export function Tag({ kind, children }: { kind?: string; children: ReactNode }) {
  return <span className={`tag tag-${kind ?? 'neutral'}`}>{children}</span>;
}
