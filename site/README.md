# Site — the publication front end

Static Astro site that renders the articles the engine writes to
`content/posts/*.md`. The engine (the Trend Content Engine, TCE) is internal;
everything this site renders is the **publication brand**, which is why the name
below is configurable and a build guardrail fails on any engine name that leaks
into `dist/`.

```bash
npm install
npm run build      # output in dist/
npm run dev        # local dev server on :4321
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `SITE_URL` | `https://example.com` | Absolute origin used for canonicals, sitemap, RSS and OG image URLs. No trailing slash. |
| `PUBLIC_BRAND_NAME` | `Upwire` | The publication name (wordmark, titles, JSON-LD, RSS, OG images). Mirrors `BRAND_NAME`. |
| `PUBLIC_BRAND_TAGLINE` | `What's rising in tech and AI, with sources.` | One-line description of the publication. Mirrors `BRAND_TAGLINE`. |
| `PUBLIC_CF_ANALYTICS_TOKEN` | unset | Cloudflare Web Analytics beacon token. Nothing loads when unset. |
| `PUBLIC_BUTTONDOWN_USERNAME` | unset | Buttondown username for the subscribe form. Renders nothing when unset. |

## Structure

* `src/layouts/BaseLayout.astro` — head, SEO/OG/Twitter tags, JSON-LD, header/footer.
* `src/components/` — header, footer, post card, analytics, subscribe.
* `src/pages/` — home, post, tag index + tag pages, archive, about, 404, `rss.xml`,
  `robots.txt` and build-time OG images under `/og/`.
* `src/lib/site.ts` — publication identity (`PUBLIC_BRAND_*`), URLs, dates, reading time, sorting, tags.
* `scripts/check-brand.mjs` — build guardrail: fails if the engine name appears in `dist/`.
* `src/lib/og.ts` — satori + resvg 1200×630 OG images.
* `src/content.config.ts` — the strict Zod schema; a malformed post fails the build.

Generated posts are produced by the Python engine (`python -m src.main`), not
hand-authored, and are restored from the `state` branch in CI.
