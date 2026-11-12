/**
 * Readable topics.
 *
 * Frontmatter carries two kinds of tag: the ingestion source (`arxiv`,
 * `hackernews`, `github`, `reddit`) and arXiv categories (`cs-ai`, `cs-lg`, …).
 * A source is never a topic — it belongs in a "Sources:" line — and a category
 * is only shown when this file knows how to read it. Anything else is hidden
 * rather than displayed as a slug.
 */
import type { Post } from "./site";

/** Ingestion sources, and how a reader should see them. */
export const SOURCE_LABELS: Record<string, string> = {
  arxiv: "arXiv",
  hackernews: "Hacker News",
  github: "GitHub",
  reddit: "Reddit",
};

/** arXiv categories worth naming; everything else stays hidden. */
export const TOPIC_LABELS: Record<string, string> = {
  "cs-ai": "AI",
  "cs-lg": "Machine learning",
  "cs-cl": "Language",
  "cs-ro": "Robotics",
  "cs-cv": "Computer vision",
  "cs-cr": "Security",
};

/** URL-safe slug for a readable label ("Machine learning" → "machine-learning"). */
export function topicSlug(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Public path of a topic page. */
export function topicHref(label: string): string {
  return `/topics/${topicSlug(label)}`;
}

/** Reader-facing name of one source value ("hackernews" → "Hacker News"). */
export function sourceLabel(raw: string): string {
  const key = (raw || "").trim().toLowerCase();
  if (!key) return "";
  return SOURCE_LABELS[key] ?? key;
}

/** Distinct, readable topics for a post, in frontmatter order. */
export function topicLabels(post: Post): string[] {
  const seen = new Set<string>();
  const labels: string[] = [];
  for (const tag of post.data.tags) {
    const label = TOPIC_LABELS[tag];
    if (!label || seen.has(label)) continue;
    seen.add(label);
    labels.push(label);
  }
  return labels;
}

/** Distinct, readable sources for a post, as listed in its frontmatter. */
export function sourceNames(post: Post): string[] {
  const seen = new Set<string>();
  const names: string[] = [];
  for (const item of post.data.sources ?? []) {
    const label = sourceLabel(item.source);
    if (!label || seen.has(label)) continue;
    seen.add(label);
    names.push(label);
  }
  return names;
}

export interface TopicSummary {
  label: string;
  slug: string;
  articles: number;
  lastDate: Date;
}

/** Every topic covered by *posts*, most-covered first. */
export function topicSummaries(posts: Post[]): TopicSummary[] {
  const rows = new Map<string, TopicSummary>();
  for (const post of posts) {
    for (const label of topicLabels(post)) {
      const row =
        rows.get(label) ?? { label, slug: topicSlug(label), articles: 0, lastDate: post.data.date };
      row.articles += 1;
      if (post.data.date > row.lastDate) row.lastDate = post.data.date;
      rows.set(label, row);
    }
  }
  return [...rows.values()].sort(
    (a, b) =>
      b.articles - a.articles ||
      b.lastDate.valueOf() - a.lastDate.valueOf() ||
      a.label.localeCompare(b.label),
  );
}

/** Posts that carry *label* as a readable topic. */
export function postsWithTopic(posts: Post[], label: string): Post[] {
  return posts.filter((post) => topicLabels(post).includes(label));
}
