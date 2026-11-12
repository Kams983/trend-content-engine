# Trend Content Engine — Implementation Plan

Status: written before any code change, per the operating rules.

## 1. What exists today (audited 2026-10-11)

| Area | File | Notes |
| --- | --- | --- |
| Orchestrator | `src/main.py` | top-to-bottom script, hard-coded `SITE_URL=""`, `print`-free but no run outcomes, catches nothing structurally |
| Ingest | `src/ingest/{hackernews,arxiv,reddit,github_trending}.py` | each builds its own `requests` calls, no shared retry/backoff, own User-Agent |
| Normalize | `src/ingest/normalize.py` | stdlib HTML strip, common schema — good, keep |
| Cluster | `src/analysis/cluster.py` | greedy single-linkage union-find over cosine similarity — chained unrelated items together; now greedy centroid assignment |
| Embed | `src/analysis/embed.py` | eager `SentenceTransformer` load at import |
| Score | `src/analysis/score.py` | **identity is the cluster label** (first title) → novelty ≈ 1.0 and velocity ≈ 1.0 every day; size/source diversity ignored |
| Generate | `src/generate/draft_article.py` | hard-codes `openai/gpt-oss-120b`, docstring still says llama, returns `None` both for "no API key" and "thin day" |
| Prompt | `src/generate/prompts/article_prompt.txt` | user-authored voice rules — **do not change**, append-only |
| Publish | `src/publish/{site,bluesky,telegram}_poster.py` | site writes markdown; bluesky uses `atproto.Client.send_post`; telegram uses Bot API |
| Fixtures | `src/ingest/fixtures/` | 4 sources × 30 = **120 frozen items** (json + jsonl) |
| Site | `site/` | Astro 7.2.9 minimal starter, 2 pages, no layout/SEO/RSS/sitemap |
| Tests | `src/ingest/fixtures/test_fixtures.py` | fixture shape validator only, not a pytest suite |

Python 3.12.10, atproto 0.0.71, astro 7.2.9, node 24.

## 2. Target architecture

```
src/
  config.py            typed Settings, .env loading, fail-fast multi-key validation
  util/http.py         ONE requests session: UA, timeout, backoff+jitter, Retry-After, 429/5xx
  util/logging.py      key=value one-line logs
  util/text.py         slugify, grapheme counting, json extraction, url normalisation
  state/db.py          connection + idempotent migrations (articles, publications, run_log, topics)
  state/repo.py        repository functions over the above
  ingest/*             use util.http; arXiv polite-usage spacing + UA
  analysis/embed.py    lazy, injectable encoder (tests never touch the network/model)
  analysis/cluster.py  unchanged algorithm, shared build_embed_text
  analysis/topics.py   centroid identity: match vs last 14d at cos>=threshold, else new topic_id
  analysis/score.py    velocity/novelty by topic_id + size/source/engagement terms, weighted
  generate/draft_article.py  injectable LLM, GROQ_MODEL + fallback, backoff
  generate/validate.py       schema/words/URLs/placeholder/dup checks + one regeneration
  publish/*            site, bluesky, telegram, devto, hashnode, mastodon — all idempotent
  orchestrator.py      stage A (draft) and stage B (publish), run outcomes, alerts
  main.py              CLI: --use-fixtures --dry-run --mode {draft,publish,full}
```

### Run outcomes (explicit, never conflated)

`PUBLISHED`, `PENDING_APPROVAL`, `SKIPPED_THIN`, `SKIPPED_NO_DATA`, `FAILED_<STAGE>`.

`PENDING_APPROVAL` is not a failure. `None` is never returned in place of a reason.

### Topic identity (fixes the core defect)

* Each day's cluster gets a 384-d centroid stored as a blob.
* A cluster matches the most similar topic centroid from the last **14 days**
  when cosine similarity ≥ `TOPIC_SIMILARITY_THRESHOLD` (0.6). Otherwise it is a
  new `topic_id` (monotonic integer).
* `velocity = today_count / mean_daily_count(last 7 days for that topic_id)`;
  default 1.0 only when there is genuinely no history.
* `novelty = 1` iff the topic_id is new this run.
* `score = w_v*vel + w_n*nov + w_s*log1p(size) + w_d*distinct_sources + w_e*engagement_percentile`.
* Eligibility: ≥ `MIN_CLUSTER_ITEMS` items (3) and ≥ `MIN_CLUSTER_SOURCES` distinct (2).
* Cooldown: topic published within `COOLDOWN_DAYS` (7) is ineligible unless `velocity ≥ 2.0`.
* History older than 60 days is pruned.

### Publishing = two stages

* **Stage A** (`--mode draft`): ingest → cluster → score → draft → validate → store
  row in `articles` with status `pending_approval` (or `drafting` when
  `REQUIRE_APPROVAL=false`).
* **Stage B** (`--mode publish`): for each article awaiting publication, publish to
  each enabled target exactly once, guarded by the `publications` table
  (unique `(article_id, target)`) → same-day reruns are no-ops.

Approval arrives as a Telegram callback (`approve:<id>` / `reject:<id>`); the
`publish` stage is also runnable on a schedule for anything already approved.

### Determinism / offline

`--use-fixtures` skips live ingest and reads the frozen fixtures. When no
`GROQ_API_KEY` is present **and** `--dry-run --use-fixtures` are both set, a
deterministic offline stub LLM is used so a fresh clone can smoke-test the whole
pipeline; this is logged loudly. Any other mode without a key fails at startup.

## 3. New dependencies — justification

| Dep | Why | Alternative rejected |
| --- | --- | --- |
| `pytest` | required test runner | — |
| `python-dotenv` | already installed and used for `.env` | hand-rolled parser |
| `grapheme` | Bluesky 300-grapheme limit is not len(); needed for correct truncation | `regex` `\X` (heavier, already present but grapheme is explicit) |
| `@astrojs/sitemap` | SEO requirement | hand-written sitemap |
| `@astrojs/rss` | full-content RSS requirement | hand-written XML |
| `satori` + `@resvg/resvg-js` | per-post 1200×630 OG image at build time (`astro-og-canvas` would also pull these in) | none — needed for images |

Everything else uses the stdlib + already-installed `requests`, `numpy`,
`sentence-transformers`, `atproto==0.0.71`, `torch` (CPU wheel).

## 4. Phase order & acceptance

0 Hygiene → 1 loud failures → 2 scoring/topic identity → 3 quality/grounding →
4 publishing/reliability → 5 state persistence → 6 alerts → 7 workflows → 8 frontend → tests → docs.

Commit after each phase (conventional commits, local only, never push).
Run the full pytest suite after every phase.

## 5. Deviations from this plan (recorded after implementation)

* **`CLUSTER_THRESHOLD` is 0.45, and clustering is centroid-based.** Single-linkage
  (union-find) at 0.40 chained across near-duplicates: one live ingest of 119
  items produced a 16-item cluster mixing mainframe emulation, agentic policy
  papers and robotics, because A≈B and B≈C merged A with C. `cluster()` now
  assigns each item to the closest *centroid* above the threshold, so a chain
  neighbour no longer drags in unrelated items. At 0.45 the same live ingest
  tops out at 3-item clusters, while the 120 fixtures still yield two eligible
  (3+ items, 2+ sources) clusters, which the tests assert. The trade-off is
  fewer eligible candidates per day: ~1 instead of 4 on that ingest, so thin
  days skip rather than draft from a mixed blob. 0.42 restores recall (~3
  eligible) at the cost of 5–7 item clusters; set `CLUSTER_THRESHOLD` to taste.
* **Extra outcomes.** `DRAFTED` (stage A succeeded with `REQUIRE_APPROVAL=false`)
  was added, because `PUBLISHED` would be a lie at that point. Individual ingest
  failures are recorded as `SOURCE_FAILED`, deliberately *not* prefixed with
  `FAILED_` so they never trigger an alert (only whole-stage `FAILED_<STAGE>`
  outcomes alert).
* **`src/generate/llm.py`** was split out of `draft_article.py` so the LLM can be
  injected, which is what makes the offline stub and the hermetic tests possible.
* **Same-day drafting guard.** Stage A no-ops if an article already exists for
  the current UTC day. Without it a rerun would draft a *different* article from
  the next eligible cluster — not a duplicate publish, but still unwanted.
* **`TCE_OFFLINE`** was added so CI and fresh clones can run the whole pipeline
  (including the site publish) with no key and no network.
* **Fonts / OG images:** `satori` + `@resvg/resvg-js` (allowed) rather than
  `astro-og-canvas`. Satori 0.47 fails to parse the Google Fonts variable TTFs
  (`Cannot read properties of undefined (reading '256')`), so static 400/600
  instances of Work Sans (SIL OFL 1.1) were generated once with `fonttools` and
  committed as assets. `fonttools` is a one-off local build tool and is **not** a
  project dependency.
* **`pytest.ini`** added with `pythonpath = .` so `src` imports and the hermetic
  fixture encoder work without a `conftest`-based path hack.
* **The fallback model needs an explicit reasoning effort.** `openai/gpt-oss-20b`
  is a reasoning model and bills its thinking to the same `max_tokens` budget:
  at the default effort it answered `content: ""` with `finish_reason: "length"`
  (2046 of 2048 completion tokens were `reasoning_tokens`), so a 429 on the
  primary model silently cost the day's article. `GroqLLM` now sends
  `reasoning_effort: "low"` to any `gpt-oss` model — 20–140 reasoning tokens,
  400–580-word drafts that validate, 5–14 s per call — and retries a
  budget-truncated response once at 8192 tokens before moving to the next
  model. A response still truncated at that budget is treated as a failure of
  that model, because half a JSON object is not a draft.
* **`python-dotenv` was already installed**, so no new runtime dependency beyond
  `grapheme` was needed on the Python side.
* Content generated by the engine is committed to the repo (the `state` branch is
  the production source); the repo ships one hand-written welcome post
  (`ai_assisted: false`) so the Astro collection is never empty.
* **Site rebuild trigger.** `publish.yml` records whether a run actually wrote a
  new post (`site/content/posts` grew) and only then calls the optional
  Cloudflare Pages deploy hook (`CF_DEPLOY_HOOK_URL`), because an article changes
  the `state` branch and nothing on `main` would otherwise rebuild the site. It
  is a logged no-op when the secret is not set.
* **Public brand split from the engine name.** The engine keeps the name Trend
  Content Engine (TCE) for everything internal — the repo, the package, the
  tables, the `TCE_*` env prefix, the `state` branch, log lines, the tests and
  these docs. Everything a reader can see is driven by `BRAND_NAME` /
  `BRAND_TAGLINE` (plus `PUBLIC_BRAND_NAME` / `PUBLIC_BRAND_TAGLINE` for the site
  build), defaulting to *Upwire*, defined once in `src/config.py` and once in
  `site/src/lib/site.ts`. Outbound templates share a single attribution shape
  (`Read more on <brand>: <url>`, `src/publish/base.py`), the site's identity flows
  from `SITE.title` so one value renames the wordmark, titles, JSON-LD, RSS and OG
  images, and the drafting prompt receives the brand through `{{publication}}`
  tokens instead of hard-coding it. Two guardrails hold the line:
  `tests/test_branding.py` in Python and `site/scripts/check-brand.mjs`, which
  runs inside `npm run build` and fails if the engine name reaches `dist/`.

## 6. Site UI redesign (2026-10-11) — what was wrong with the first UI

Audited the shipped Astro front end before changing anything. The pipeline, the
content schema, the routes, the SEO/RSS/sitemap output and the zero-client-JS
constraint are untouched by this pass; only CSS, layouts and templates changed.

| Problem | Why it matters |
| --- | --- |
| Serif headings over a sans body, both at generic sizes | No hierarchy: the page title, post titles and index rows all compete. A publication should lead with type. |
| `.section-head` H1 "Latest" plus a post counter at the top of the home page | A large heading and a meaningless number push the actual article down the page. |
| Boxes and pills: bordered tag chips (`border-radius: 999px`), a boxed `.disclosure` with an accent left border, bordered `pre` and inputs | Reads as a generic app template rather than an editorial page, and the pill is the loudest element in a row. |
| Accent `#255e8a` used for body links | Links compete with the prose, and the accent is not reserved for interaction. |
| Header printed "DAILY TREND DIGEST" in tracked-out uppercase | Reads as a widget label, and it hid the tagline, which is the honest description of the publication. |
| Pure-white surfaces on a `#f8f7f4` page; dark mode `#121316` with `#ecedee` text | Surfaces popped out of the page, and dark mode was harsher than it needed to be. |
| Secondary text at `0.78–0.9rem`, hairlines `#e3e1db` | Too small to read comfortably, and the rule nearly vanished against the page. |
| Disclosure, tags and sources styled as components rather than as text | The AI-assistance note is a fact about the article, not a callout; sources are references, not bullets to decorate. |
| Nav had no current-page state; the footer mixed prose, links and copyright in one row | No orientation while browsing, and the footer did not line up with the content column. |
| No print stylesheet | Printing carried the navigation and the footer. |

Specific fixes applied to the home page (raised before the redesign, all done):
the "Latest" H1 and the counter are now a small muted section label; the article
title is the dominant element; teasers are muted and smaller than titles; tag
pills are plain muted text; the footer disclosure sits in the same column as the
header and content as a quiet small footer; the header label is the tagline in
normal case; the SVG mark sits beside the wordmark; the current nav item has an
accent state; and dark mode uses off-white `#EDEDED` text on `#0F0F10`.

### Second pass: what the review found and changed

Round one was reviewed with rendered screenshots plus DOM measurement at 375,
768 and 1280 in both colour schemes (scripts kept out of the repo: the browser
audit measured geometry, computed type, contrast and tap targets, and a pixel
pass read the finished PNGs for band rhythm and column alignment). Nine flaws
were found and fixed:

| Flaw (evidence) | Fix |
| --- | --- |
| Home's `<h1>` was the word "Latest" (rendered tiny), so the page's only h1 was a label and the document outline was nonsense. | The masthead is the home page's `h1`, visually hidden; the visible label is `<p class="section-label">`, small, muted, normal case. |
| Page titles on Archive, Tags, tag and 404 pages rendered at 12px uppercase, identically to the small labels, so those pages had no dominant element (computed 12px vs the h1 scale in the brief). | `.page-title` gives them the real h1 scale: 32px at 375, 44px at 1280, weight 700. |
| The reading column measured 770px at 1280, over the 720px cap: `66ch` is wider than 720px in the fallback serif of this machine. | `--measure: min(66ch, 45rem)`; the article and every teaser now measure 720px. |
| The current nav item was drawn with `box-shadow: inset 0 -2px 0`, which the house style bans (rules and whitespace only). | A real underline: 2px, accent, 6px offset. |
| Body links were underlined in `--hairline` (#e6e4de on #fafaf7, about 1.15:1): in prose, links looked like plain text. | Underline at `color-mix(in srgb, currentColor 45%, transparent)`, still 1px with a 3px offset. |
| Tag separators used the same hairline colour, so tags ran together. | Muted separators with 0.45em spacing. |
| Row titles were set at line-height 1.15, which crowds a title that wraps to two or three lines. | 1.3. |
| No `color-scheme`, so dark mode still painted light scrollbars and form furniture. | `color-scheme: light` on `:root`, `dark` under `prefers-color-scheme: dark`. |
| Archive rows, the tag index and the source list had 17 to 31px tap targets on touch widths. | Those list links get a 44px minimum target up to tablet width; the footer links get vertical padding. |

Verified after the changes: no horizontal overflow at any of the three widths
(the off-screen skip link is the only element past the viewport), every band on
a page starts at the same left edge as the header and the footer (160px at 1280,
31px at 768, 20px at 375), the reading column is 720px, all text pairs stay at
or above 5.1:1 in light mode and 6.8:1 in dark mode, the tagline is one line
instead of two, and no radius above 4px, shadow, gradient, sticky element or
`<img>` exists anywhere. `npm run build` and `npm run check:brand` pass, the
built output contains one CSS file and no JavaScript beyond the two JSON-LD
blocks on post pages.

Not verified: Lighthouse was not installed on this machine and was not added, so
no Lighthouse score is reported. The preview panel would not composite for the
full 30-image eyeball pass, so the screenshots in `docs/screenshots/` were
reviewed by looking at the home page at 1280 and live mobile renders directly,
and by a pixel audit of the saved PNGs (ground colour, content bands, gaps,
left edges, hairline runs) rather than by eye at every breakpoint.
