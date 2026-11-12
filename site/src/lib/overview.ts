/**
 * Build-time data for the dashboard at /board.
 *
 * Pure: posts in, plain data out — no Astro imports, no clock. The window ends
 * at the newest post's date rather than at build time, so a build on a quiet
 * morning shows the last edition instead of a row of zeros, and every build of
 * the same content produces the same output. Bar heights and widths are
 * computed here from the content, never hardcoded in the template.
 */
import type { Post } from "./site";
import { formatDayShort, sortPosts } from "./site";
import { sourceLabel, topicSummaries, type TopicSummary } from "./topics";

const DAY_MS = 86_400_000;

/** The board reports on the last week of published articles. */
export const WINDOW_DAYS = 7;

/** Plot height in px for the publishing-rhythm chart. */
const PLOT_HEIGHT = 140;

const weekdayLong = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" });
const weekdayNarrow = new Intl.DateTimeFormat("en-US", { weekday: "narrow", timeZone: "UTC" });
const longDay = new Intl.DateTimeFormat("en-US", { month: "long", day: "numeric", timeZone: "UTC" });

export interface BoardDay {
  iso: string;
  articles: number;
  /** Bar height in px; empty days get the 2px stub. */
  heightPx: number;
  weekday: string;
  weekdayNarrow: string;
  isToday: boolean;
}

export interface BoardSource {
  name: string;
  count: number;
  /** Bar width as a percentage of the largest source. */
  widthPct: number;
}

export interface BoardTopic extends TopicSummary {
  /** "Oct 11" — the last date this topic was covered in the window. */
  lastLabel: string;
}

export interface Board {
  windowStart: Date;
  windowEnd: Date;
  windowLabel: string;
  articleCount: number;
  sourceCount: number;
  /** Every topic the table can list; the "topics covered" tile equals this. */
  topics: BoardTopic[];
  topicCount: number;
  publicationDays: number;
  windowDays: number;
  perArticle: string;
  topTopic: string;
  days: BoardDay[];
  sources: BoardSource[];
}

export const startOfUtcDay = (date: Date): Date =>
  new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));

export function buildBoard(posts: Post[], windowDays = WINDOW_DAYS): Board | null {
  if (posts.length === 0) return null;

  const sorted = sortPosts(posts);
  const windowEnd = startOfUtcDay(sorted[0].data.date);
  const windowStart = new Date(windowEnd.getTime() - (windowDays - 1) * DAY_MS);
  const inWindow = sorted.filter((post) => startOfUtcDay(post.data.date) >= windowStart);

  const days: BoardDay[] = [];
  for (let offset = 0; offset < windowDays; offset += 1) {
    const date = new Date(windowStart.getTime() + offset * DAY_MS);
    const iso = date.toISOString().slice(0, 10);
    days.push({
      iso,
      articles: 0,
      heightPx: 2,
      weekday: weekdayLong.format(date),
      weekdayNarrow: weekdayNarrow.format(date),
      isToday: date.getTime() === windowEnd.getTime(),
    });
  }

  const sourceTotals = new Map<string, number>();
  for (const post of inWindow) {
    const day = days.find((candidate) => candidate.iso === startOfUtcDay(post.data.date).toISOString().slice(0, 10));
    if (day) day.articles += 1;
    for (const item of post.data.sources ?? []) {
      const name = sourceLabel(item.source);
      if (!name) continue;
      sourceTotals.set(name, (sourceTotals.get(name) ?? 0) + 1);
    }
  }

  const maxArticles = Math.max(1, ...days.map((day) => day.articles));
  for (const day of days) {
    day.heightPx =
      day.articles === 0
        ? 2
        : Math.max(10, Math.round((day.articles / maxArticles) * PLOT_HEIGHT));
  }

  const sourceCount = [...sourceTotals.values()].reduce((sum, count) => sum + count, 0);
  const maxSource = Math.max(0, ...sourceTotals.values());
  const sources: BoardSource[] = [...sourceTotals.entries()]
    .map(([name, count]) => ({
      name,
      count,
      widthPct: maxSource > 0 ? Math.round((count / maxSource) * 100) : 0,
    }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));

  const topics: BoardTopic[] = topicSummaries(inWindow).map((row) => ({
    ...row,
    lastLabel: formatDayShort(row.lastDate),
  }));

  return {
    windowStart,
    windowEnd,
    windowLabel: `${longDay.format(windowStart)} to ${longDay.format(windowEnd)}`,
    articleCount: inWindow.length,
    sourceCount,
    topics,
    topicCount: topics.length,
    publicationDays: days.filter((day) => day.articles > 0).length,
    windowDays,
    perArticle: inWindow.length > 0 ? (sourceCount / inWindow.length).toFixed(1) : "0.0",
    topTopic: topics[0]?.label ?? "",
    days,
    sources,
  };
}
