# Trend Content Engine (TCE)

An unattended daily publishing system. It ingests trending items from four
sources, clusters them by embedding similarity, scores the clusters against a
persistent topic history, drafts one grounded article with an LLM, validates it,
and publishes it to a static Astro site plus optional social targets — exactly
once per day.

Everything is small pure-function modules, plain Python, `requests` for HTTP and
SQLite for state. No web framework, no ORM, no queue.

---

## Architecture

```
                    ┌───────────────────────────────────────────────┐
   GitHub Actions   │  daily.yml  (stage A)   publish.yml (stage B)  │
   concurrency:     │  ingest → cluster → score → draft → validate   │
   tce-state        │            → store draft (articles)            │
                    │  approve via Telegram  → publish → publications│
                    └───────────────┬───────────────────────────────┘
                                    │
   ┌────────────────────────────────┴─────────────────────────────────┐
   │                            src/                                  │
   │                                                                  │
   │  ingest/            normalize.py ── common item schema           │
   │   ├ hackernews  ─┐                                               │
   │   ├ arxiv        │   util/http.py  (UA, timeout, backoff+jitter, │
   │   ├ github       ├── 429/5xx retry, Retry-After)                 │
   │   └ reddit      ─┘                                               │
   │        │                                                         │
   │        ▼                                                         │
   │  analysis/embed.py (MiniLM, 384-d, lazy)                         │
   │        │                                                         │
   │        ▼                                                         │
   │  analysis/cluster.py ── union-find over cosine similarity        │
   │        │                                                         │
   │        ▼                                                         │
   │  analysis/topics.py ── centroid identity → stable topic_id       │
   │  analysis/score.py  ── velocity/novelty/size/sources/engagement  │
   │        │                                                         │
   │        ▼                                                         │
   │  generate/draft_article.py ── Groq (configurable model + fallback)│
   │  generate/validate.py      ── schema, words, URLs, placeholders  │
   │        │                                                         │
   │        ▼                                                         │
   │  state/db.py + state/repo.py ── run_log, articles, publications, │
   │                                 topics (SQLite, idempotent DDL)  │
   │        │                                                         │
   │        ▼                                                         │
   │  publish/  site · bluesky · telegram · devto · hashnode · mastodon│
   └────────────────────────────────┬─────────────────────────────────┘
                                    │
                          site/  Astro (static)
                          home · post · tags · archive · about · 404
                          RSS /rss.xml · sitemap.xml · OG images
```

## Requirements

* Python 3.12 (`pip install -r requirements.txt`)
* Node 22.12+ for the site (`cd site && npm install`)
* Optional: `GROQ_API_KEY`, Telegram bot, Bluesky app password, DEV.to key.

## Setup

```bash
git clone <repo> && cd <repo>
python -m venv .venv && . .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
cp .env.example .env            # then fill it in
```

Full manual setup (accounts, secrets, DNS, rollout) is in [docs/SETUP.md](docs/SETUP.md).

## Run modes

| Command | What it does |
| --- | --- |
| `python -m src.main --use-fixtures --dry-run` | Fully offline smoke test on the frozen fixtures. No network, no posts. |
| `python -m src.main --dry-run` | Live ingest + real LLM, but nothing is posted or written. |
| `python -m src.main --mode draft` | Stage A only: produce a draft and store it (awaiting approval). |
| `python -m src.main --mode publish` | Stage B only: publish everything already approved. |
| `python -m src.main` | Full pipeline (stage A + B). |

Same-day reruns are safe: every publish is recorded in `publications` and
skipped on the second attempt, and stage A refuses to draft a second article for
the same UTC day.

`TCE_OFFLINE=1` forces the deterministic stub writer (no Groq key needed) so you
can exercise the whole pipeline locally.

Engine state (the SQLite database and `site/content/posts`) lives on a
single-commit `state` branch. CI moves it in and out with:

```bash
python -m src.state.persist restore   # before the pipeline
python -m src.state.persist save      # after it (force-pushes refs/heads/state)
```

Local development quickstart: [docs/SETUP.md](docs/SETUP.md)

## Environment variables

See [`.env.example`](.env.example) for the authoritative list with comments.
The important ones:

| Key | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | — | LLM access (required unless offline smoke test) |
| `TCE_OFFLINE` | `false` | force the deterministic stub writer (no key, no network) |
| `GROQ_MODEL` / `GROQ_MODEL_FALLBACK` | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` | chat models |
| `REQUIRE_APPROVAL` | `true` | wait for Telegram approve/reject before publishing |
| `DRY_RUN` | `false` | do everything except outbound posts |
| `SITE_URL` | — | absolute site URL, used for links |
| `ENABLE_BLUESKY` / `ENABLE_TELEGRAM_CHANNEL` / `ENABLE_DEVTO` | `false` | social targets |
| `ENABLE_HASHNODE` / `ENABLE_MASTODON` | `false` | optional targets |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ADMIN_CHAT_ID` | — | approval + alerts |
| `MIN_CLUSTER_ITEMS` / `MIN_CLUSTER_SOURCES` | `3` / `2` | article eligibility |
| `TOPIC_SIMILARITY_THRESHOLD` | `0.6` | centroid match threshold |

## Tests

```bash
python -m pytest -q
```

All network access is mocked; the embedding model is replaced by a deterministic
encoder so the suite is fast and hermetic. One end-to-end test runs the whole
pipeline on fixtures with a mocked LLM and mocked publishers and asserts the
final database state.

## Ops runbook

1. **Missing config** → startup prints every missing key; fix `.env` and rerun.
2. **`SKIPPED_THIN`** → no cluster met the eligibility bar (≥3 items, ≥2 sources).
   Expected on quiet days; not an error.
3. **`SKIPPED_NO_DATA`** → fewer than `MIN_SOURCES_WITH_DATA` sources returned
   data. Check the source status lines in the log and upstream status pages.
4. **`FAILED_<STAGE>`** → the stage name is in the run log; the failure is
   recorded and a Telegram alert is sent.
5. **Approval** → drafts arrive in the admin chat with Approve / Reject buttons.
   Approve triggers the publish stage.
6. **Rerunning a day** → safe. `publications` makes publishing idempotent.
7. **State** → `trend_store.sqlite` plus `site/content/posts/*.md` are pushed
   to the orphan `state` branch by CI (single-commit, force-push; history never grows).

## Licence

Internal project. No stock imagery; all content generated from cited sources.
