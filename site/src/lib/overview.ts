/**
 * Build-time numbers for the home board.
 *
 * Pure: posts in, plain data out — no Astro imports, no clock. The window ends
 * at the newest post's date rather than at build time, so a build on a quiet
 * morning shows the last edition instead of a row of zeros, and every build of
 * the same content produces the same output.
 */
import type { Post } from "./site";
import { formatDayShort, sortPosts } from "./site";

const DAY_MS = 86_400_000;
const DEFAULT_WINDOW_DAYS = 7;
const TOPIC_LIMIT = 5;
const SOURCE_LIMIT = 6;

const narrowWeekday = new Intl.DateTimeFormat("en-US", { weekday: "narrow", timeZone: "UTC" });
const longWeekday = new Intl.DateTimeFormat("en-US", { weekday: "long", timeZone: "UTC" });
const longDay = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", timeZone: "UTC" });

export interface DayMark {
  date: Date;
  weekday: string;
  articles: number;
  sources: number;
}

export interface TopicRow {
  tag: string;
  posts: number;
  sources: number;
  lastDate: Date;
}

export interface SourceRow {
  name: string;
  count: number;
  shareOfMax: number;
}

export interface Overview {
  days: DayMark[];
  windowDays: number;
  windowEnd: Date;
  windowLabel: string;
  stripLabel: string;
  articleCount: number;
  sourceCount: number;
  topicCount: number;
  publicationDays: number;
  quietDays: number;
  sourcesPerArticle: number;
  topTopic: string;
  topicRows: TopicRow[];
  sourceRows: SourceRow[];
}

const startOfUtcDay = (date: Date): Date =>
  new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));

const dayKey = (date: Date): string => startOfUtcDay(date).toISOString().slice(0, 10);

export function buildOverview(posts: Post[], windowDays = DEFAULT_WINDOW_DAYS): Overview | null {
  if (posts.length === 0) return null;

  const sorted = sortPosts(posts);
  const windowEnd = startOfUtcDay(sorted[0].data.date);
  const windowStart = new Date(windowEnd.getTime() - (windowDays - 1) * DAY_MS);
  const inWindow = sorted.filter((post) => startOfUtcDay(post.data.date) >= windowStart);

  const days: DayMark[] = [];
  for (let offset = 0; offset < windowDays; offset += 1) {
    const date = new Date(windowStart.getTime() + offset * DAY_MS);
    const key = date.toISOString().slice(0, 10);
    const ofDay = inWindow.filter((post) => dayKey(post.data.date) === key);
    days.push({
      date,
      weekday: narrowWeekday.format(date),
      articles: ofDay.length,
      sources: ofDay.reduce((sum, post) => sum + post.data.sources.length, 0),
    });
  }

  const sourceCount = inWindow.reduce((sum, post) => sum + post.data.sources.length, 0);

  const byTag = new Map<string, TopicRow>();
  for (const post of inWindow) {
    for (const tag of post.data.tags) {
      const row = byTag.get(tag) ?? { tag, posts: 0, sources: 0, lastDate: post.data.date };
      row.posts += 1;
      row.sources += post.data.sources.length;
      if (post.data.date > row.lastDate) row.lastDate = post.data.date;
      byTag.set(tag, row);
    }
  }
  const topicRows = [...byTag.values()]
    .sort(
      (a, b) =>
        b.sources - a.sources ||
        b.posts - a.posts ||
        b.lastDate.valueOf() - a.lastDate.valueOf() ||
        a.tag.localeCompare(b.tag),
    )
    .slice(0, TOPIC_LIMIT);

  const bySource = new Map<string, number>();
  for (const post of inWindow) {
    for (const item of post.data.sources) {
      const name = item.source || "other";
      bySource.set(name, (bySource.get(name) ?? 0) + 1);
    }
  }
  const maxSource = Math.max(0, ...bySource.values());
  const sourceRows = [...bySource.entries()]
    .map(([name, count]) => ({ name, count, shareOfMax: maxSource > 0 ? count / maxSource : 0 }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .slice(0, SOURCE_LIMIT);

  const publicationDays = days.filter((day) => day.articles > 0).length;
  const windowLabel = `${formatDayShort(windowStart)} to ${formatDayShort(windowEnd)}`;
  const stripLabel = [
    `Sources cited per day, ${longDay.format(windowStart)} to ${formatDayShort(windowEnd)}:`,
    ...days.map((day) => `${longWeekday.format(day.date)} ${day.sources}`),
  ].join(" ");

  return {
    days,
    windowDays,
    windowEnd,
    windowLabel,
    stripLabel,
    articleCount: inWindow.length,
    sourceCount,
    topicCount: byTag.size,
    publicationDays,
    quietDays: windowDays - publicationDays,
    sourcesPerArticle: inWindow.length > 0 ? sourceCount / inWindow.length : 0,
    topTopic: topicRows[0]?.tag ?? "",
    topicRows,
    sourceRows,
  };
}
