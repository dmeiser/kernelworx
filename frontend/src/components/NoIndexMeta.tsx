/**
 * Meta tag component to prevent search engines from indexing the page.
 */
import { useEffect } from 'react';

export const NoIndexMeta: React.FC = () => {
  useEffect(() => {
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex';
    document.head.appendChild(meta);

    return () => {
      document.head.removeChild(meta);
    };
  }, []);

  return null;
};