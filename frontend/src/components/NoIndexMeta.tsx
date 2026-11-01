/**
 * Meta tag component to prevent search engines from indexing the page.
 *
 * React 19 natively hoists `<meta>` elements rendered in the component tree
 * into `<head>` and manages their lifecycle (inserted on mount, removed on
 * unmount), so no imperative DOM manipulation is needed.
 */
export const NoIndexMeta: React.FC = () => <meta name="robots" content="noindex" />;
