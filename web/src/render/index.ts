/**
 * The message renderer: Markdown, GFM tables, and KaTeX mathematics.
 *
 * `renderMarkdown` is the slot the Design System's `MessageContent` takes; everything
 * research-specific (resolving `rh://`, deciding what a reference may show) stays in the
 * app, which is why the only hook out of here is `onDeepLink`.
 */
export { Markdown, parseDeepLink, renderMarkdown } from './markdown';
export type { CodeBlock, DeepLink, MarkdownOptions, MarkdownProps } from './markdown';
