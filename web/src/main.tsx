/**
 * The cockpit's entry point.
 *
 * `@research-harness/design/styles.css` is imported before any application CSS, so the
 * package's token layer, themes and base rules are in force and `styles.css` only adds
 * what is genuinely application layout. `ThemeProvider` writes `data-theme` /
 * `data-density` onto the document element — dark is the default (plan §0.6) — and
 * `ToastProvider` gives every surface one place to report that a mutation landed.
 *
 * `HostProvider` is outside the router's content but inside the router, because which host
 * answered decides which route tree exists at all (design §11). The session — one workspace
 * and the principal the daemon assigns us in it — is mounted further in, by `App`, since a
 * multi-project host has one session per project rather than one for the whole window.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@research-harness/design';
import '@research-harness/design/styles.css';
import { App } from './app/App';
import { HostProvider } from './app/host';
import './styles.css';

const root = document.getElementById('root');
if (!root) throw new Error('index.html has no #root');

createRoot(root).render(
  <StrictMode>
    <ThemeProvider defaultTheme="dark" defaultDensity="comfortable">
      <ToastProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <HostProvider>
            <App />
          </HostProvider>
        </BrowserRouter>
      </ToastProvider>
    </ThemeProvider>
  </StrictMode>,
);
