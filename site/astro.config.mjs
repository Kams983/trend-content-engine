// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// Single source of truth for the public origin. `SITE_URL` has no trailing
// slash everywhere (the Python publishers build links the same way).
const SITE_URL = (process.env.SITE_URL || 'https://example.com').replace(/\/+$/, '');

// https://astro.build/config
export default defineConfig({
  site: SITE_URL,
  // Consistent trailing-slash behaviour: /posts/<slug> (no slash anywhere).
  trailingSlash: 'never',
  build: { format: 'file' },
  compressHTML: true,
  integrations: [sitemap()],
});
