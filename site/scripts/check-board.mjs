// Board contract check.
//
// Re-derives the dashboard's numbers from the content frontmatter with an
// independent, deliberately naive parser, then asserts that the built pages
// show the same values. It reads dist/, so it catches template mistakes as well
// as a board that has drifted from the content.
//
// The rule is unchanged: every number on the board must come from the posts'
// frontmatter. Two extra contracts are enforced here because they are easy to
// break silently:
//   * the "topics covered" tile equals the number of rows the table lists, and
//   * below BOARD_MIN_ARTICLES the board renders nothing and the header does
//     not link to it.
//
// Run it after `npm run build`.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WINDOW_DAYS = 7;
const DAY_MS = 86_400_000;
const PLOT_HEIGHT = 140;

// Duplicated from src/lib/topics.ts on purpose: this script must derive the
// expected labels without importing the code the site renders with.
const TOPIC_LABELS = {
  "cs-ai": "AI",
  "cs-lg": "Machine learning",
  "cs-cl": "Language",
  "cs-ro": "Robotics",
  "cs-cv": "Computer vision",
  "cs-cr": "Security",
};
const SOURCE_LABELS = {
  arxiv: "arXiv",
  hackernews: "Hacker News",
  github: "GitHub",
  reddit: "Reddit",
};

const here = dirname(fileURLToPath(import.meta.url));
const siteRoot = join(here, "..");
const postsDir = join(siteRoot, "content", "posts");
const homePath = join(siteRoot, "dist", "index.html");
const boardPath = join(siteRoot, "dist", "board.html");

const longDay = new Intl.DateTimeFormat("en-US", {
  month: "long",
  day: "numeric",
  timeZone: "UTC",
});
const shortDay = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

function startOfUtcDay(date) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}

const dayKey = (date) => startOfUtcDay(date).toISOString().slice(0, 10);

function scalar(raw) {
  const value = raw.trim();
  if (value.startsWith('"') && value.endsWith('"')) {
    return value.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  }
  return value;
}

function parsePost(name, raw) {
  const text = raw.replace(/\r\n/g, "\n");
  const close = text.indexOf("\n---", 4);
  const front = text.slice(4, close === -1 ? undefined : close);
  let section = "";
  const tags = [];
  const sourceNames = [];
  let sourceCount = 0;
  let title = "";
  let description = "";
  let date = "";
  for (const line of front.split("\n")) {
    if (/^[a-z][a-z_]*:/.test(line)) {
      section = line.slice(0, line.indexOf(":"));
      const rest = line.slice(line.indexOf(":") + 1).trim();
      if (section === "title") title = scalar(rest);
      if (section === "description") description = scalar(rest);
      if (section === "date") date = scalar(rest);
      continue;
    }
    if (section === "tags" && /^ {2}- /.test(line)) tags.push(scalar(line.slice(4)));
    if (section === "sources" && /^ {2}- title:/.test(line)) sourceCount += 1;
    if (section === "sources" && /^ {4}source:/.test(line)) sourceNames.push(scalar(line.slice(line.indexOf(":") + 1)));
  }
  return { name, title, description, date: new Date(date), tags, sourceCount, sourceNames };
}

function readPosts() {
  return readdirSync(postsDir)
    .filter((name) => name.endsWith(".md"))
    .map((name) => parsePost(name, readFileSync(join(postsDir, name), "utf8")));
}

/** Readable topics for a post: known arXiv categories only, never a source. */
function topicsOf(post) {
  const labels = [];
  for (const tag of post.tags) {
    const label = TOPIC_LABELS[tag];
    if (label && !labels.includes(label)) labels.push(label);
  }
  return labels;
}

/** Distinct readable sources for a post. */
function sourcesOf(post) {
  const labels = [];
  for (const raw of post.sourceNames) {
    const label = SOURCE_LABELS[raw.trim().toLowerCase()];
    if (label && !labels.includes(label)) labels.push(label);
  }
  return labels;
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
const matchAll = (html, pattern) => [...html.matchAll(pattern)];

const siteConfig = readFileSync(join(siteRoot, "src", "lib", "site.ts"), "utf8");
const BOARD_MIN_ARTICLES = Number(/BOARD_MIN_ARTICLES\s*=\s*(\d+)/.exec(siteConfig)?.[1] ?? 10);

const posts = readPosts();
if (posts.length === 0) {
  console.log("check:board — no posts yet, the board is not expected to render");
  process.exit(0);
}

const errors = [];
const requireThat = (ok, message) => {
  if (!ok) errors.push(message);
};

// --- expected board numbers, straight from the frontmatter ------------------

const newest = posts.reduce((a, b) => (a.date > b.date ? a : b));
const windowEnd = startOfUtcDay(newest.date);
const windowStart = new Date(windowEnd.getTime() - (WINDOW_DAYS - 1) * DAY_MS);
const inWindow = posts.filter((post) => startOfUtcDay(post.date) >= windowStart);

const articlesPerDay = new Map();
for (const post of inWindow) {
  const key = dayKey(post.date);
  articlesPerDay.set(key, (articlesPerDay.get(key) ?? 0) + 1);
}
const dayCounts = [];
for (let offset = 0; offset < WINDOW_DAYS; offset += 1) {
  const key = new Date(windowStart.getTime() + offset * DAY_MS).toISOString().slice(0, 10);
  dayCounts.push({ iso: key, count: articlesPerDay.get(key) ?? 0 });
}

const sourceTotals = new Map();
for (const post of inWindow) {
  for (const raw of post.sourceNames) {
    const label = SOURCE_LABELS[raw.trim().toLowerCase()];
    if (!label) continue;
    sourceTotals.set(label, (sourceTotals.get(label) ?? 0) + 1);
  }
}
const sourceCount = [...sourceTotals.values()].reduce((sum, count) => sum + count, 0);
const rankedSources = [...sourceTotals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
const maxSource = rankedSources.length ? rankedSources[0][1] : 0;

const byTopic = new Map();
for (const post of inWindow) {
  for (const label of topicsOf(post)) {
    const row = byTopic.get(label) ?? { articles: 0, lastDate: post.date };
    row.articles += 1;
    if (post.date > row.lastDate) row.lastDate = post.date;
    byTopic.set(label, row);
  }
}
// Must match buildBoard(): articles, then recency, then label.
const rankedTopics = [...byTopic.entries()].sort(
  (a, b) =>
    b[1].articles - a[1].articles ||
    b[1].lastDate - a[1].lastDate ||
    a[0].localeCompare(b[0]),
);

const expected = {
  windowLabel: `${longDay.format(windowStart)} to ${longDay.format(windowEnd)}`,
  articles: inWindow.length,
  sources: sourceCount,
  topics: rankedTopics.length,
  publicationDays: dayCounts.filter((day) => day.count > 0).length,
  perArticle: (inWindow.length ? sourceCount / inWindow.length : 0).toFixed(1),
  topTopic: rankedTopics[0]?.[0] ?? "",
};

const maxArticles = Math.max(1, ...dayCounts.map((day) => day.count));
const expectedBarHeight = (count) =>
  count === 0 ? 2 : Math.max(10, Math.round((count / maxArticles) * PLOT_HEIGHT));

// --- home page: lead + earlier list ----------------------------------------

const homeHtml = readFileSync(homePath, "utf8");
const homeText = visibleText(homeHtml);
const earlierPosts = posts.filter((post) => post.name !== newest.name);

requireThat(homeText.includes(newest.title), `home page shows the newest title “${newest.title}”`);
requireThat(
  countMatches(homeHtml, 'class="row"') === earlierPosts.length,
  `${earlierPosts.length} earlier rows`,
);
for (const post of earlierPosts) {
  requireThat(homeText.includes(post.title), `earlier list shows “${post.title}”`);
}

const leadTeaser = /<p class="lead__teaser">([\s\S]*?)<\/p>/.exec(homeHtml)?.[1] ?? "";
requireThat(leadTeaser.length > 0, "lead story has a teaser");
requireThat(!/https?:\/\//.test(leadTeaser), "lead teaser contains no URL");
requireThat(!/was reported by/i.test(leadTeaser), "lead teaser is not scraped boilerplate");
requireThat(!homeHtml.includes('data-stat="'), "home page does not duplicate the board");

// --- board page -------------------------------------------------------------

const rendered = posts.length >= BOARD_MIN_ARTICLES;
if (!existsSync(boardPath)) {
  requireThat(!rendered, "board.html exists");
} else {
  const boardHtml = readFileSync(boardPath, "utf8");
  if (!rendered) {
    requireThat(
      !boardHtml.includes('data-stat="'),
      `board stays empty below ${BOARD_MIN_ARTICLES} articles`,
    );
    requireThat(!homeHtml.includes('href="/board"'), "header does not link to an empty board");
  } else {
    const boardText = visibleText(boardHtml);
    const statValue = (key) =>
      Number(
        new RegExp(`data-stat="${key}"[\\s\\S]{0,400}?stat__value">(\\d+)<`).exec(boardHtml)?.[1] ?? NaN,
      );
    const statSub = (key) =>
      new RegExp(`data-stat="${key}"[\\s\\S]{0,400}?stat__sub">([^<]+)<`)
        .exec(boardHtml)?.[1]
        ?.trim() ?? "";

    requireThat(boardText.toLowerCase().includes("the week"), "eyebrow “The week”");
    requireThat(boardText.includes(expected.windowLabel), `window heading “${expected.windowLabel}”`);

    requireThat(statValue("articles") === expected.articles, "articles-published tile");
    requireThat(
      statSub("articles") === `On ${expected.publicationDays} of ${WINDOW_DAYS} days`,
      "articles tile sub-label",
    );
    requireThat(statValue("sources") === expected.sources, "sources-cited tile");
    requireThat(statSub("sources") === `${expected.perArticle} per article`, "sources tile sub-label");
    requireThat(statValue("topics") === expected.topics, "topics-covered tile");
    requireThat(
      statSub("topics") === (expected.topTopic ? `Most covered: ${expected.topTopic}` : "No topics yet"),
      "topics tile sub-label",
    );

    // Publishing rhythm: seven columns, counts and computed bar heights.
    const rhythm = matchAll(boardHtml, /data-day="([\d-]+)" data-count="(\d+)"/g).map((match) => ({
      iso: match[1],
      count: Number(match[2]),
    }));
    requireThat(rhythm.length === WINDOW_DAYS, `${WINDOW_DAYS} rhythm columns`);
    dayCounts.forEach((day, index) => {
      const column = rhythm[index];
      requireThat(column?.iso === day.iso, `rhythm column ${index + 1} is ${day.iso}`);
      requireThat(column?.count === day.count, `rhythm count for ${day.iso}`);
      const block = new RegExp(
        `data-day="${day.iso}" data-count="${day.count}"[\\s\\S]{0,600}?`,
      ).exec(boardHtml);
      const slice = boardHtml.slice(block?.index ?? 0, (block?.index ?? 0) + 700);
      if (day.count === 0) {
        requireThat(slice.includes("rhythm__bar--empty"), `empty stub for ${day.iso}`);
      } else {
        requireThat(
          slice.includes(`height:${expectedBarHeight(day.count)}px`),
          `bar height for ${day.iso} (${day.count} article(s))`,
        );
      }
    });
    requireThat(
      countMatches(boardHtml, "rhythm__col--today") === 1,
      "one column is marked as the window end",
    );
    requireThat(
      new RegExp(`rhythm__col--today[^"]*" data-day="${dayKey(windowEnd)}"`).test(boardHtml),
      "the marked column is the newest post's day",
    );

    // Where it came from: one row per source with a proportional bar.
    const rows = matchAll(boardHtml, /data-source="([^"]+)" data-count="(\d+)"/g).map((match) => ({
      name: match[1],
      count: Number(match[2]),
    }));
    requireThat(rows.length === rankedSources.length, `${rankedSources.length} source rows`);
    rankedSources.forEach(([name, count], index) => {
      requireThat(rows[index]?.name === name, `source row ${index + 1} is ${name}`);
      requireThat(rows[index]?.count === count, `source count for ${name}`);
      const start = boardHtml.indexOf(`data-source="${name}"`);
      const slice = boardHtml.slice(start, start + 400);
      const width = Number(/width:(\d+)%/.exec(slice)?.[1] ?? NaN);
      requireThat(
        width === (maxSource > 0 ? Math.round((count / maxSource) * 100) : 0),
        `bar width for ${name}`,
      );
      // The class list sits before data-source on the same element.
      const openTag = boardHtml.slice(boardHtml.lastIndexOf("<li", start), start);
      if (index === 0) requireThat(openTag.includes("src--lead"), "the largest source is accented");
    });
    requireThat(
      boardText.includes(
        `${expected.sources} source${expected.sources === 1 ? "" : "s"} across ` +
          `${expected.articles} article${expected.articles === 1 ? "" : "s"}`,
      ),
      "source summary line",
    );

    // What is rising: one row per topic; the tile must equal the row count.
    const rising = matchAll(boardHtml, /data-topic="([^"]+)" data-count="(\d+)"/g).map((match) => ({
      label: match[1],
      articles: Number(match[2]),
    }));
    requireThat(rising.length === rankedTopics.length, `${rankedTopics.length} rising rows`);
    requireThat(rising.length === statValue("topics"), "topics tile equals the rows it lists");
    rankedTopics.forEach(([label, row], index) => {
      requireThat(rising[index]?.label === label, `rising row ${index + 1} is ${label}`);
      requireThat(rising[index]?.articles === row.articles, `article count for ${label}`);
      const start = boardHtml.indexOf(`data-topic="${label}"`);
      const slice = boardHtml.slice(start, start + 600);
      requireThat(
        slice.includes(shortDay.format(row.lastDate)),
        `last-covered date for ${label}`,
      );
      requireThat(slice.includes('href="/topics/'), `${label} links to its topic page`);
    });
  }
}

if (errors.length > 0) {
  console.error("check:board — the board does not match the content:");
  for (const error of errors) console.error(`  - ${error}`);
  process.exit(1);
}

const plural = (count, word) => `${count} ${word}${count === 1 ? "" : "s"}`;
console.log(
  rendered
    ? `check:board — board matches the content window (${plural(expected.articles, "article")}, ` +
        `${plural(expected.sources, "source")}, ${plural(expected.topics, "topic")})`
    : `check:board — board correctly hidden (${plural(posts.length, "article")}, ` +
        `below the ${BOARD_MIN_ARTICLES}-article threshold)`,
);
