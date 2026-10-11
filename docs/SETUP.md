# Setup — every manual step, in order

This is the list of things a human has to do. Nothing here can be automated by
the engine (accounts, secrets, DNS, hosting). Work top to bottom.

Never paste a secret into chat, a commit, an issue comment or a log. Secrets go
into GitHub → Settings → Secrets and variables → Actions, or into `.env` locally
(which is gitignored).

---

## 1. Local prerequisites

| Tool | Version |
| --- | --- |
| Python | 3.12 |
| Node | 22.12+ (24 tested) |
| git | any recent |

```bash
git clone <your-fork-or-repo> && cd <repo>
python -m venv .venv && . .venv/Scripts/activate      # Windows
# python -m venv .venv && . .venv/bin/activate        # macOS/Linux
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
cd site && npm ci && cd ..
cp .env.example .env
```

The `--extra-index-url` line is required: without it pip pulls the ~2 GB CUDA
torch wheels. The engine only ever runs on CPU.

## 2. Verify locally, offline, before touching any account

```bash
python -m pytest -q                                    # 147 tests, no network
python -m src.main --use-fixtures --dry-run             # full pipeline, nothing sent
```

Both must be green. The second command deliberately works with an empty `.env`:
with `--use-fixtures --dry-run` and no `GROQ_API_KEY` it uses a deterministic
stub writer and sends nothing.

Running the real pipeline against the frozen fixtures without approval, to
produce local content:

```bash
TCE_OFFLINE=1 REQUIRE_APPROVAL=false python -m src.main --use-fixtures
cd site && npm run build
```

## 3. GitHub repository + Actions secrets

Create the repo, push `main`. Then **Settings → Secrets and variables → Actions**.

### 3a. Secrets (encrypted)

| Secret name | Required? | How to get it |
| --- | --- | --- |
| `GROQ_API_KEY` | yes | console.groq.com → API Keys |
| `TELEGRAM_BOT_TOKEN` | yes (approval + alerts) | @BotFather → `/newbot` |
| `TELEGRAM_ADMIN_CHAT_ID` | yes (approval + alerts) | see §6 |
| `TELEGRAM_CHANNEL_ID` | if `ENABLE_TELEGRAM_CHANNEL` | see §6 |
| `BLUESKY_HANDLE` | if `ENABLE_BLUESKY` | your handle, e.g. `you.bsky.social` |
| `BLUESKY_APP_PASSWORD` | if `ENABLE_BLUESKY` | Bluesky Settings → App Passwords |
| `DEVTO_API_KEY` | if `ENABLE_DEVTO` | dev.to Settings → Extensions → DEV API Keys |
| `HASHNODE_API_KEY` | if `ENABLE_HASHNODE` | Hashnode Settings → Developer → PAT |
| `HASHNODE_PUBLICATION_ID` | if `ENABLE_HASHNODE` | Hashnode → blog dashboard → publication id |
| `MASTODON_INSTANCE` | if `ENABLE_MASTODON` | e.g. `https://mastodon.social` |
| `MASTODON_ACCESS_TOKEN` | if `ENABLE_MASTODON` | instance → Preferences → Development → New application (write scope) |

### 3b. Variables (plain text, non-secret)

| Variable name | Example | Notes |
| --- | --- | --- |
| `SITE_URL` | `https://trend.example.com` | origin only, **no trailing slash** |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | optional; overrides the default |
| `GROQ_MODEL_FALLBACK` | `openai/gpt-oss-20b` | optional |
| `ENABLE_BLUESKY` | `false` | flip to `true` in step 9 |
| `ENABLE_TELEGRAM_CHANNEL` | `false` | flip to `true` in step 9 |
| `ENABLE_DEVTO` | `false` | flip to `true` in step 9 |
| `ENABLE_HASHNODE` | `false` | needs a Hashnode **Pro** plan (see §8) |
| `ENABLE_MASTODON` | `false` | flip to `true` in step 9 |

Workflow permissions are already correct in `.github/workflows/*.yml`
(`contents: write` for the two state-writing workflows, `contents: read` for CI).

## 4. Groq

1. Create an API key at <https://console.groq.com/keys>.
2. Add it as the `GROQ_API_KEY` secret.
3. Optional: set `GROQ_MODEL` / `GROQ_MODEL_FALLBACK` variables. The default is
   `openai/gpt-oss-120b` with `openai/gpt-oss-20b` as the fallback after a
   retryable failure.

## 5. The `state` branch

The runner is ephemeral, so the SQLite database and the generated posts live on
a branch called `state` that always holds **exactly one commit** (it is force
pushed on every run, so its history never grows).

* Nothing to create by hand: the first `python -m src.state.persist save` creates
  the branch, and the first `restore` treats a missing branch as a clean no-op.
* To seed it locally (e.g. from your fixture run in §2):

```bash
python -m src.state.persist save --message "state: seed from fixtures"
```

That pushes to `origin` by default; add `--no-push` to keep it local.

## 6. Telegram bot, channel and admin chat id

1. Message **@BotFather** → `/newbot` → copy the token → `TELEGRAM_BOT_TOKEN`.
2. **Admin chat id** (receives approvals and failure alerts):
   * Message your bot directly, then open
     `https://api.telegram.org/bot<TOKEN>/getUpdates` and read
     `result[0].message.chat.id` — that number is `TELEGRAM_ADMIN_CHAT_ID`.
3. **Channel** (optional, only if `ENABLE_TELEGRAM_CHANNEL=true`):
   * Create the channel, add the bot as an **administrator** with post rights.
   * Use `@yourchannel` as `TELEGRAM_CHANNEL_ID`, or the numeric
     `-100…` id from `getUpdates`.
4. Approvals use inline buttons; the `publish-approved` workflow polls for them
   hourly, so a tap is picked up within the hour (or immediately on a manual run).

## 7. Static hosting + subdomain DNS

The site is a plain static build (`site/dist`), intended to live on its own
subdomain (e.g. `trend.example.com`).

### Cloudflare Pages (recommended)

1. Cloudflare dashboard → Workers & Pages → Create → Pages → connect the repo.
2. **Build settings**
   * Root directory: `site`
   * Build command: `npm ci && npm run build`
   * Build output directory: `dist`
3. **Environment variables** (Production *and* Preview)

   | Name | Value |
   | --- | --- |
   | `SITE_URL` | `https://trend.example.com` |
   | `PUBLIC_CF_ANALYTICS_TOKEN` | optional, see §11 |
   | `PUBLIC_BUTTONDOWN_USERNAME` | optional, see §11 |

4. Because posts live on the `state` branch, add a build step that restores them
   before building — set the build command to:

   ```
   git fetch --depth=1 origin state:state || true; git restore --source=state -- site/content/posts || true; cd site && npm ci && npm run build
   ```

   (with Root directory left empty), or add the same two `git` lines to a
   `prebuild` npm script.
5. Pages → Custom domains → add `trend.example.com`, then create the DNS record
   Cloudflare asks for (usually a `CNAME` to `<project>.pages.dev`, or an `A`/
   `AAAA` record if the zone is on Cloudflare and proxied).

### Vercel / Netlify (alternative)

* **Vercel**: Root Directory `site`, Framework `Astro`, Build `npm run build`,
  Output `dist`; same environment variables.
* **Netlify**: Base directory `site`, Build command `npm run build`, Publish
  directory `site/dist`; same environment variables.

## 8. Optional social targets

| Target | Steps |
| --- | --- |
| Bluesky | Settings → App Passwords → create one → `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` |
| DEV.to | dev.to → Settings → Extensions → DEV API Keys → `DEVTO_API_KEY` |
| Hashnode | Settings → Developer → PAT, plus your publication id → `HASHNODE_API_KEY`, `HASHNODE_PUBLICATION_ID`. **Since 2026-05-13 the Hashnode GraphQL API requires a paid Pro plan on the publication**; it is off by default for that reason. |
| Mastodon | Preferences → Development → New application (scopes `write:statuses`) → `MASTODON_INSTANCE`, `MASTODON_ACCESS_TOKEN` |

## 9. Rollout checklist

Do this in order. Each step is a gate — do not proceed until the previous one is
boring.

1. **Local dry run** — `python -m src.main --use-fixtures --dry-run` and
   `pytest`. Confirm `--dry-run` logs what it *would* send and writes nothing.
2. **CI green** — push to `main`; the `ci` workflow must pass `pytest`, the
   offline smoke test and the Astro build.
3. **Live dry run in CI** — Actions → `daily-draft` → Run workflow with
   `use_fixtures=false`, `dry_run=true`. Read the logs: sources ingested, the
   chosen topic, the draft, and the previews. Nothing is posted and no state is
   saved.
4. **Approval mode with real Telegram** — keep `REQUIRE_APPROVAL=true`, add the
   Groq and Telegram secrets, then run `daily-draft` *without* `dry_run`. A
   draft should arrive in the admin chat with **Approve & publish** /
   **Reject**. Tap Reject first and confirm the article is rejected (no post
   anywhere). Next day (or on a manual run) tap Approve and confirm exactly one
   post appears on the site and that `publish-approved` reports `PUBLISHED`.
5. **Site only** — with `SITE_URL` set and all `ENABLE_*` still `false`, let a
   real run publish. Verify the page, its OG image, the RSS item and the
   canonical URL.
6. **Enable social targets one at a time** — flip exactly one of
   `ENABLE_TELEGRAM_CHANNEL`, `ENABLE_BLUESKY`, `ENABLE_DEVTO`, `ENABLE_MASTODON`
   (and `ENABLE_HASHNODE` only if you have Pro), run `publish-approved`
   manually, and check the post before enabling the next one. Re-running is
   safe: each `(article, target)` pair is recorded once, so nothing is posted
   twice.
7. **Turn on the schedule** — the crons in `daily.yml` (07:17 UTC) and
   `publish.yml` (hourly) are already active; nothing to enable.
8. **Optional extras** — Buttondown and Cloudflare Web Analytics (§11).
9. **Alert drill** — temporarily break something (e.g. remove
   `GROQ_API_KEY` from one manual run) and confirm the `if: failure()` step
   posts a Telegram alert even when Python itself failed.

## 10. Scheduled-workflow caveat

GitHub disables a **public** repository's scheduled workflows after 60 days with
no repository activity. Every run force-pushes a commit to the `state` branch,
which is repository activity, so the timer does not trip in practice. If a run
ever is missed, re-enable it in the Actions tab or use **Run workflow**
(`workflow_dispatch` is wired up on both workflows). Private repositories are
not affected by that rule.

## 11. Optional extras

* **Cloudflare Web Analytics** — dashboard → Analytics → Web Analytics → add the
  site → copy the beacon token into the Pages variable
  `PUBLIC_CF_ANALYTICS_TOKEN`. The beacon renders nothing when it is unset.
* **Buttondown** — create a free newsletter, then set the Pages variable
  `PUBLIC_BUTTONDOWN_USERNAME` to your username. The subscribe form renders
  nothing when it is unset.

## 12. Runbook

| Symptom | Meaning | Action |
| --- | --- | --- |
| Startup exits 2 and lists keys | config incomplete | fill `.env` / GitHub secrets, re-run |
| `SKIPPED_THIN` | no cluster had ≥3 items from ≥2 sources | normal on quiet days; lower `MIN_CLUSTER_ITEMS` only if you accept thinner posts |
| `SKIPPED_NO_DATA` | fewer than 2 sources returned data (alert sent) | check the source status lines in the log and upstream status pages |
| `FAILED_INGEST/CLUSTER/SCORE/DRAFT/VALIDATE/PUBLISH` | that stage failed; recorded in `run_log` | read the reason, fix, re-run `--mode draft` or `--mode publish` |
| `PENDING_APPROVAL` | a draft is waiting on Telegram | approve/reject in the admin chat |
| Draft arrives twice in one day | it should not — the same-day guard prevents it | if it does, check `run_log` for the `articles` rows and open an issue |
| Push of the `state` branch fails | token/permission problem | confirm `contents: write` is still granted to the workflow |
| Site shows no posts | state not restored before the build | check the restore step in the hosting build command (§7.4) |
| `git restore --source=state` fails | first ever run, no branch yet | expected no-op; ignore |
