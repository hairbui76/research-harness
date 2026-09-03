import type { ReactElement, ReactNode } from 'react';
import { PdfPreview } from './PdfPreview';
import { failedBuild, noToolchainBuild, succeededBuild } from '../manuscript.specimen-data';

/** Stands in for the application's pdf.js adapter. */
function page(index: number, scale: number): ReactNode {
  return (
    <div
      className="rh-surface-paper"
      style={{
        inlineSize: `${Math.round(420 * scale)}px`,
        blockSize: `${Math.round(560 * scale)}px`,
        border: '1px solid var(--rh-border-on-paper)',
        borderRadius: 'var(--rh-radius-card)',
        padding: 'var(--rh-space-5)',
        fontFamily: 'var(--rh-font-serif)',
      }}
    >
      <h3 style={{ marginTop: 0 }}>Thermal tolerance under sustained load</h3>
      <p>{`Page ${index} at ${Math.round(scale * 100)}%.`}</p>
      <p>
        The application renders this with pdf.js; the Design System only frames it, pages
        it and reports where the researcher is.
      </p>
    </div>
  );
}

function Framed({ children }: { children: ReactNode }): ReactElement {
  return <div className="gallery-frame-fixed">{children}</div>;
}

export const title = 'PdfPreview';

export const specimens = [
  {
    name: 'A current PDF',
    render: () => (
      <Framed>
        <PdfPreview
          build={succeededBuild}
          pageCount={12}
          defaultPage={3}
          renderPage={page}
          onSearch={() => undefined}
          onInverseSync={() => undefined}
        />
      </Framed>
    ),
  },
  {
    name: 'Stale — the last good PDF after a failed build',
    render: () => (
      <Framed>
        <PdfPreview build={failedBuild} pageCount={12} renderPage={page} onSearch={() => undefined} />
      </Framed>
    ),
  },
  {
    name: 'No toolchain — setup guidance instead of a blank pane',
    render: () => (
      <Framed>
        <PdfPreview build={noToolchainBuild} />
      </Framed>
    ),
  },
  {
    name: 'Nothing compiled yet',
    render: () => (
      <Framed>
        <PdfPreview build={{ status: 'idle', synctex: 'unavailable' }} />
      </Framed>
    ),
  },
];
