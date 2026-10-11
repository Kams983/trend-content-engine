# Trend Content Engine — Implementation Plan

Status: written before any code change, per the operating rules.

## 1. What exists today (audited 2026-10-11)

| Area | File | Notes |
| --- | --- | --- |
| Orchestrator | `src/main.py` | top-to-bottom script, hard-coded `SITE_URL=""`, `print`-free but no run outcomes, catches nothing structurally |
| Ingest | `src/ingest/{hackernews,arxiv,reddit,github_trending}.py` | each builds its own `requests` calls, no shared retry/backoff, own User-Agent |
| Normalize | `src/ingest/normalize.py` | stdlib HTML strip, common schema — good, keep |
| Cluster | `src/analysis/cluster.py` | greedy union-find over cosine similarity — good, keep |
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

* **`CLUSTER_THRESHOLD` tuned to 0.40**, not the inherited 0.45. Measured on the
  120 fixtures (see `scripts/precompute_fixture_embeddings.py`): 0.40 yields four
  eligible clusters with a 12-item / 2-source top cluster, while 0.45 leaves two
  and 0.38 starts merging unrelated topics into a 14-item blob.
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
