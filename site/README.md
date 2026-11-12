# Site — the publication front end

Static Astro site that renders the articles the engine writes to
`content/posts/*.md`. The engine (the Trend Content Engine, TCE) is internal;
everything this site renders is the **publication brand**, which is why the name
below is configurable and a build guardrail fails on any engine name that leaks
into `dist/`.

```bash
npm install
npm run build      # dist/, then the guardrails below
npm run dev        # local dev server on :4321
```

The build ends with two guardrails, so a broken page fails the build rather than
deploying: `check:brand` fails if an engine name leaks into `dist/`, and
`check:board` re-derives the home page's numbers from `content/posts/*.md` and
asserts the built page matches.

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
* `src/lib/overview.ts` — the home board's numbers (window, cadence, topics, source mix). Pure: posts
  in, plain data out, no clock, so every build of the same content is identical.
* `src/components/CadenceStrip.astro`, `MetricTiles.astro`, `TopicTable.astro`, `SourceBars.astro` —
  the home board's sections; `PostCard.astro` also renders each row of the home feed.
* `scripts/check-brand.mjs` — build guardrail: fails if the engine name appears in `dist/`.
* `scripts/check-board.mjs` — build guardrail: parses the post frontmatter independently and fails if
  the built home page's numbers, cards or cadence ticks disagree with the content.
* `src/lib/og.ts` — satori + resvg 1200×630 OG images.
* `src/content.config.ts` — the strict Zod schema; a malformed post fails the build.

Generated posts are produced by the Python engine (`python -m src.main`), not
hand-authored, and are restored from the `state` branch in CI.
