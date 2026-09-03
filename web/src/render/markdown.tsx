/**
 * The conversation's Markdown + mathematics renderer.
 *
 * The LaTeX spec (§2) draws the line this module sits on: a *message* renders Markdown and
 * KaTeX as presentation, and rendering an expression here never claims that a manuscript
 * compiles. Real LaTeX goes through the local toolchain on the Manuscript route.
 *
 * The rules this renderer keeps, because a chat surface is where untrusted model output
 * meets a researcher's browser:
 *
 * - **Raw HTML is never rendered.** `react-markdown` turns raw nodes into text, and no
 *   `rehype-raw` is installed. A `<script>` in a message is a visible string, not a script.
 * - **Nothing loads from the network.** KaTeX's CSS and fonts are imported from the
 *   package, and a remote `![image](https://…)` is shown as a link rather than fetched, so
 *   a message cannot make the workstation call out (`allowRemoteImages` opts back in).
 * - **A broken expression is a marker, not a crash.** `rehype-katex` renders with
 *   `throwOnError: false` under the hood and hands back a `.katex-error` span; the
 *   `rehypeMathErrors` transform below turns that into an accessible, token-styled marker
 *   carrying the source that failed.
 * - **Mathematics exposes text to assistive technology** (conversation spec §9):
 *   `output: 'htmlAndMathml'` emits MathML beside the visual HTML, and the MathML carries
 *   an `annotation` with the original TeX.
 * - **`rh://` deep links do not navigate.** They are handed to `onDeepLink` so the app can
 *   resolve the object, check authority and privacy, and move the inspector (§0.1, §7).
 *   External links open in a new tab with `rel="noopener noreferrer"`.
 *
 * The Design System's `MessageContent` takes a `renderMarkdown(text) => ReactNode` slot;
 * `renderMarkdown` here is exactly that function, and `<Markdown text=… />` is the same
 * thing as a component.
 */
import 'katex/dist/katex.min.css';
import './markdown.css';

import { useMemo } from 'react';
import type { ComponentPropsWithoutRef, ReactNode } from 'react';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import type { Components, ExtraProps, Options } from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

/** One `rh://<kind>/<id>[?query]` reference, parsed but *not* resolved (plan §0.1). */
export interface DeepLink {
  /** The href exactly as it was written in the message. */
  readonly href: string;
  /** `artifact`, `evidence`, `claim`, `session`, `attachment`, `manuscript`, … */
  readonly kind: string;
  /** The object id or, for `manuscript`, the workspace-relative path. */
  readonly id: string;
  /** `?page=6&block=B0081`, `?line=120`, `?message=M0042`, … */
  readonly params: URLSearchParams;
}

/** One fenced code block, handed to `renderCode` so a copy control can be wired to it. */
export interface CodeBlock {
  /** The block's text, without the trailing newline the parser keeps. */
  readonly code: string;
  /** The info string after the fence (`ts`, `bibtex`, …), or null when there was none. */
  readonly language: string | null;
}

export interface MarkdownOptions {
  /** Called instead of navigating when an `rh://` link is activated. */
  onDeepLink?: (link: DeepLink) => void;
  /** Replaces the default `<pre><code class="language-…">`; the copy affordance goes here. */
  renderCode?: (block: CodeBlock) => ReactNode;
  /** Extra classes on the wrapper, beside `rh-md`. */
  className?: string;
  /**
   * Load `![…](https://…)` images. Off by default: a message is untrusted input, and
   * fetching an image named in it is an egress the researcher did not ask for.
   */
  allowRemoteImages?: boolean;
}

export interface MarkdownProps extends MarkdownOptions {
  /** The message text: Markdown with GFM tables, `$inline$` and `$$display$$` maths. */
  text: string;
}

/**
 * KaTeX settings.
 *
 * `throwOnError` is deliberately absent: `rehype-katex` 7 owns it (its option type omits
 * the field) and always falls back to `throwOnError: false`, which is the behaviour we
 * want — one bad expression marks itself and the rest of the message still renders.
 *
 * `maxSize`/`maxExpand` bound what a model can ask the renderer to do; `trust: false` is
 * KaTeX's default and is stated here because it is what keeps `\href`, `\url` and
 * `\includegraphics` out of a message.
 */
const KATEX_OPTIONS = {
  output: 'htmlAndMathml',
  strict: 'ignore',
  trust: false,
  maxSize: 50,
  maxExpand: 1000,
} as const;

const REMARK_PLUGINS: NonNullable<Options['remarkPlugins']> = [remarkGfm, remarkMath];
const REHYPE_PLUGINS: NonNullable<Options['rehypePlugins']> = [
  [rehypeKatex, KATEX_OPTIONS],
  rehypeMathErrors,
];

const DEEP_LINK = /^rh:\/\/([A-Za-z][A-Za-z0-9_]*)\/([^?#]+)(?:\?([^#]*))?(?:#.*)?$/;

/** Parse `rh://claim/C0041?x=1`. Returns null for anything that is not a deep link. */
export function parseDeepLink(href: string): DeepLink | null {
  const match = DEEP_LINK.exec(href.trim());
  if (!match) return null;
  const [, kind, id, query] = match;
  if (!kind || !id) return null;
  let decoded = id;
  try {
    decoded = decodeURIComponent(id);
  } catch {
    // A malformed escape is the message's problem, not ours: keep the raw id.
  }
  return { href, kind: kind.toLowerCase(), id: decoded, params: new URLSearchParams(query ?? '') };
}

/**
 * Render one message body.
 *
 * This is the `renderMarkdown` slot `MessageContent` asks for; bind the options once and
 * pass `(text) => renderMarkdown(text, options)`.
 */
export function renderMarkdown(text: string, options: MarkdownOptions = {}): ReactNode {
  return <Markdown text={text} {...options} />;
}

/** The same renderer as a component, for callers that would rather write JSX. */
export function Markdown({ text, className, ...options }: MarkdownProps) {
  const { onDeepLink, renderCode, allowRemoteImages } = options;
  const components = useMemo(
    () => buildComponents({ onDeepLink, renderCode, allowRemoteImages }),
    [onDeepLink, renderCode, allowRemoteImages],
  );
  return (
    <div className={className ? `rh-md ${className}` : 'rh-md'}>
      <ReactMarkdown
        remarkPlugins={REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
        urlTransform={transformUrl}
        components={components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

/**
 * URL sanitising.
 *
 * `react-markdown`'s default drops every protocol but http(s), mailto, irc and xmpp —
 * which is what stops `javascript:` — and it would drop `rh://` with them. This keeps our
 * own scheme and delegates everything else unchanged.
 */
function transformUrl(value: string): string {
  if (DEEP_LINK.test(value.trim())) return value;
  return defaultUrlTransform(value);
}

function buildComponents(options: MarkdownOptions): Components {
  const { onDeepLink, renderCode, allowRemoteImages } = options;

  return {
    a({ node, href, children, ...rest }: ComponentPropsWithoutRef<'a'> & ExtraProps) {
      void node;
      const target = typeof href === 'string' ? href : '';
      const deepLink = target ? parseDeepLink(target) : null;

      if (deepLink) {
        // Never navigate: `rh://` is resolved by the app, which checks the project, the
        // object's existence, authority, privacy and anchor freshness first (plan §0.1).
        return (
          <a
            {...rest}
            href={target}
            className="rh-md__link rh-md__link--deep"
            data-deep-link={target}
            data-deep-link-kind={deepLink.kind}
            onClick={(event) => {
              event.preventDefault();
              onDeepLink?.(deepLink);
            }}
          >
            {children}
          </a>
        );
      }

      if (!target) return <span {...rest}>{children}</span>;

      const external = isExternal(target);
      return (
        <a
          {...rest}
          href={target}
          className="rh-md__link"
          {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
        >
          {children}
        </a>
      );
    },

    // A fenced block, not inline code: `pre` is where the whole block is addressable, and
    // so where a copy control belongs. Display maths never reaches here — `rehype-katex`
    // replaced those `<pre>` elements before React saw the tree.
    pre({ node, children, ...rest }: ComponentPropsWithoutRef<'pre'> & ExtraProps) {
      const block = codeBlockFrom(node);
      if (!block) return <pre {...rest}>{children}</pre>;
      if (renderCode) return <>{renderCode(block)}</>;
      return (
        <div className="rh-md__code" data-language={block.language ?? undefined}>
          <pre>
            <code className={block.language ? `language-${block.language}` : undefined}>
              {block.code}
            </code>
          </pre>
        </div>
      );
    },

    // A wide GFM table scrolls inside its own box rather than stretching the transcript.
    // The box is focusable and named, so it can be reached and scrolled from the keyboard.
    table({ node, children, ...rest }: ComponentPropsWithoutRef<'table'> & ExtraProps) {
      void node;
      return (
        <div className="rh-md__table-scroll" role="region" aria-label="Table" tabIndex={0}>
          <table {...rest}>{children}</table>
        </div>
      );
    },

    img({ node, src, alt, ...rest }: ComponentPropsWithoutRef<'img'> & ExtraProps) {
      void node;
      const source = typeof src === 'string' ? src : '';
      const label = typeof alt === 'string' && alt ? alt : 'image';
      if (!allowRemoteImages && isExternal(source)) {
        return (
          <a
            className="rh-md__remote-image"
            href={source}
            target="_blank"
            rel="noopener noreferrer"
            title={source}
          >
            {label} <span className="rh-md__note">(remote image, not loaded)</span>
          </a>
        );
      }
      return (
        <img
          {...rest}
          className="rh-md__image"
          src={source}
          alt={typeof alt === 'string' ? alt : ''}
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      );
    },
  };
}

/** http(s) somewhere other than the origin serving the cockpit. */
function isExternal(href: string): boolean {
  if (!href || href.startsWith('#') || href.startsWith('/') || href.startsWith('.')) return false;
  try {
    const here = globalThis.location?.href ?? 'http://127.0.0.1/';
    const url = new URL(href, here);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
    return url.origin !== new URL(here).origin;
  } catch {
    return false;
  }
}

// -- the hast side ----------------------------------------------------------------------
//
// `hast` and `unist-util-visit` are transitive dependencies of `react-markdown` rather
// than ours, so the helpers below walk the tree with a local structural type instead of
// importing types this package does not declare.

interface HastNode {
  type?: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown> | null;
  children?: HastNode[];
}

/**
 * Turn KaTeX's error span into a marker a person and a screen reader can both read.
 *
 * KaTeX's own fallback is a `katex-error` span carrying an inline `style="color:…"` with
 * a hard-coded red in it: a literal that fights the theme, and an error only a mouse can
 * find (the reason is in a `title`). This
 * replaces it with a token-styled `role="img"` marker whose label carries the expression
 * that failed, while the visible text stays the source itself.
 */
function rehypeMathErrors() {
  return (tree: unknown): undefined => {
    visit(tree as HastNode, (node) => {
      if (!classesOf(node).includes('katex-error')) return;
      const source = textOf(node);
      const title = node.properties?.title;
      node.properties = {
        className: ['rh-md__math-error'],
        role: 'img',
        'aria-label': `Mathematics that could not be rendered: ${source}`,
        title: typeof title === 'string' && title ? title : 'KaTeX could not render this',
        'data-math-source': source,
      };
    });
    return undefined;
  };
}

function visit(node: HastNode | null | undefined, visitor: (node: HastNode) => void): void {
  if (!node || typeof node !== 'object') return;
  if (node.type === 'element') visitor(node);
  for (const child of node.children ?? []) visit(child, visitor);
}

function classesOf(node: HastNode): string[] {
  const value = node.properties?.className;
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === 'string') return value.split(/\s+/);
  return [];
}

function textOf(node: HastNode): string {
  if (node.type === 'text') return String(node.value ?? '');
  return (node.children ?? []).map(textOf).join('');
}

/** The `<code>` inside a `<pre>`, as text plus the language the fence declared. */
function codeBlockFrom(node: unknown): CodeBlock | null {
  const element = node as HastNode | undefined;
  const code = element?.children?.find(
    (child) => child.type === 'element' && child.tagName === 'code',
  );
  if (!code) return null;
  const language = classesOf(code)
    .find((name) => name.startsWith('language-'))
    ?.slice('language-'.length);
  return { code: textOf(code).replace(/\n$/, ''), language: language || null };
}
