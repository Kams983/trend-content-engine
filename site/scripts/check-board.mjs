// Board contract check.
//
// Re-derives the home board's numbers from the content frontmatter with an
// independent, deliberately naive parser, then asserts that the built page
// shows the same values. It reads dist/, so it catches template mistakes as
// well as a board that has drifted from the content.
//
// Every marker is a substring of the page's visible text, or a class count for
// the cadence strip. Run it after `npm run build`.
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WINDOW_DAYS = 7;
const DAY_MS = 86_400_000;
const TOPIC_LIMIT = 5;
const SOURCE_LIMIT = 6;

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = join(here, "..");
const postsDir = join(siteRoot, "content", "posts");
const homePath = join(siteRoot, "dist", "index.html");

const shortDay = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

function startOfUtcDay(date) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}

function parsePost(name, raw) {
  const text = raw.replace(/\r\n/g, "\n");
  const close = text.indexOf("\n---", 4);
  const front = text.slice(4, close === -1 ? undefined : close);
  let section = "";
  const tags = [];
  const sourceNames = [];
  let sources = 0;
  for (const line of front.split("\n")) {
    if (/^[a-z][a-z_]*:/.test(line)) {
      section = line.slice(0, line.indexOf(":"));
      continue;
    }
    if (section === "tags" && /^ {2}- /.test(line)) tags.push(line.slice(4).replace(/^"|"$/g, ""));
    if (section === "sources" && /^ {2}- title:/.test(line)) sources += 1;
    if (section === "sources" && /^ {4}source:/.test(line)) {
      sourceNames.push(line.slice(line.indexOf(":") + 1).trim().replace(/^"|"$/g, ""));
    }
  }
  const date = /^date:\s*(.+)$/m.exec(front)?.[1]?.trim() ?? "";
  return { name, date: new Date(date), tags, sources, sourceNames };
}

function readPosts() {
  return readdirSync(postsDir)
    .filter((name) => name.endsWith(".md"))
    .map((name) => parsePost(name, readFileSync(join(postsDir, name), "utf8")));
}

/** Visible text of the page: scripts and tags stripped, whitespace collapsed. */
function visibleText(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&(?:rsquo|#8217);/g, "’")
    .replace(/&(?:#39|apos);/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

const countMatches = (html, needle) => html.split(needle).length - 1;

const posts = readPosts();
if (posts.length === 0) {
  console.log("check:board — no posts yet, the board is not expected to render");
  process.exit(0);
}

const newest = posts.reduce((a, b) => (a.date > b.date ? a : b));
const windowEnd = startOfUtcDay(newest.date);
const windowStart = new Date(windowEnd.getTime() - (WINDOW_DAYS - 1) * DAY_MS);
const inWindow = posts.filter((post) => startOfUtcDay(post.date) >= windowStart);

const byTag = new Map();
const publishedDays = new Set();
let sourceCount = 0;
for (const post of inWindow) {
  sourceCount += post.sources;
  publishedDays.add(startOfUtcDay(post.date).toISOString().slice(0, 10));
  for (const tag of post.tags) {
    const row = byTag.get(tag) ?? { posts: 0, sources: 0, lastDate: post.date };
    row.posts += 1;
    row.sources += post.sources;
    if (post.date > row.lastDate) row.lastDate = post.date;
    byTag.set(tag, row);
  }
}

// This ordering must match buildOverview(): sources, then posts, then recency,
// then the tag name, so the tile's "most covered" agrees with the table's
// first row.
const rankedTags = [...byTag.entries()].sort(
  (a, b) =>
    b[1].sources - a[1].sources ||
    b[1].posts - a[1].posts ||
    b[1].lastDate - a[1].lastDate ||
    a[0].localeCompare(b[0]),
);

const bySource = new Map();
for (const post of inWindow) {
  for (const item of post.sourceNames) {
    bySource.set(item, (bySource.get(item) ?? 0) + 1);
  }
}
const rankedSources = [...bySource.entries()].sort(
  (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
);

const expected = {
  windowLabel: `${shortDay.format(windowStart)} to ${shortDay.format(windowEnd)}`,
  articles: inWindow.length,
  sources: sourceCount,
  topics: byTag.size,
  publishedDays: publishedDays.size,
  quietDays: WINDOW_DAYS - publishedDays.size,
  perArticle: (inWindow.length ? sourceCount / inWindow.length : 0).toFixed(1),
  topTopic: rankedTags[0]?.[0] ?? "",
};

const html = readFileSync(homePath, "utf8");
const text = visibleText(html);
const failures = [];
const requireMarker = (ok, message) => {
  if (!ok) failures.push(message);
};

// --- overview strip and tiles -----------------------------------------------
requireMarker(
  text.includes(`The last ${WINDOW_DAYS} days, ${expected.windowLabel}`),
  `window caption "The last ${WINDOW_DAYS} days, ${expected.windowLabel}"`,
);
requireMarker(text.includes(`${expected.articles} articles published`), "tile: articles published");
requireMarker(text.includes(`${expected.sources} sources cited`), "tile: sources cited");
requireMarker(text.includes(`${expected.topics} topics covered`), "tile: topics covered");
requireMarker(
  text.includes(`on ${expected.publishedDays} of ${WINDOW_DAYS} days`),
  `articles tile context "on ${expected.publishedDays} of ${WINDOW_DAYS} days"`,
);
requireMarker(text.includes(`${expected.perArticle} per article`), "sources tile context");
requireMarker(text.includes(`most covered: ${expected.topTopic}`), "topics tile context");
requireMarker(countMatches(html, "strip__col") === WINDOW_DAYS, `${WINDOW_DAYS} cadence columns`);
requireMarker(
  countMatches(html, "strip__tick--published") === expected.publishedDays,
  `${expected.publishedDays} published ticks`,
);
requireMarker(
  countMatches(html, "strip__tick--quiet") === expected.quietDays,
  `${expected.quietDays} quiet ticks`,
);

// --- what's rising ----------------------------------------------------------
const topicRowCount = Math.min(TOPIC_LIMIT, rankedTags.length);
if (topicRowCount > 0) {
  requireMarker(text.includes("What’s rising"), "card heading “What's rising”");
  requireMarker(text.includes("All topics"), "topics card link");
  requireMarker(countMatches(html, "topic-row") === topicRowCount, `${topicRowCount} topic rows`);
  const top = rankedTags[0];
  requireMarker(
    text.includes(`${top[1].posts} post${top[1].posts === 1 ? "" : "s"} · ${shortDay.format(top[1].lastDate)}`),
    `top topic summary for ${top[0]}`,
  );
  requireMarker(
    countMatches(html, 'href="/tags/') >= topicRowCount,
    "topic rows link to their tag pages",
  );
}

// --- where it came from -----------------------------------------------------
if (rankedSources.length > 0) {
  const [topName, topCount] = rankedSources[0];
  requireMarker(text.includes("Where it came from"), "card heading “Where it came from”");
  requireMarker(
    text.includes(
      `${sourceCount} source${sourceCount === 1 ? "" : "s"} across ${expected.articles} article${expected.articles === 1 ? "" : "s"}`,
    ),
    "source card total",
  );
  requireMarker(
    countMatches(html, "bars__row") === Math.min(SOURCE_LIMIT, rankedSources.length),
    "bar rows",
  );
  requireMarker(countMatches(html, "width:100%") >= 1, `leading bar ${topName} (${topCount})`);
}

// --- earlier articles -------------------------------------------------------
const earlierPosts = posts.filter((post) => post.name !== newest.name);
if (earlierPosts.length > 0) {
  requireMarker(text.includes("Earlier articles"), "card heading “Earlier articles”");
  requireMarker(text.includes("Archive"), "feed card archive link");
  requireMarker(
    countMatches(html, "post-row__metrics") === earlierPosts.length,
    `${earlierPosts.length} feed metric lines`,
  );
  const minSources = Math.min(...earlierPosts.map((post) => post.sources));
  const quietLabel =
    minSources === 0 ? "no sources" : `${minSources} source${minSources === 1 ? "" : "s"}`;
  requireMarker(text.includes(quietLabel), `feed meta shows “${quietLabel}”`);
}

if (failures.length > 0) {
  console.error("check:board — the board does not match the content window:");
  for (const failure of failures) console.error(`  - missing: ${failure}`);
  process.exit(1);
}

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
console.log(
  `check:board — board matches the content window (${plural(expected.articles, "article")}, ` +
    `${plural(expected.sources, "source")}, ${plural(expected.topics, "topic")})`,
);
