import type { CollectionEntry } from "astro:content";

/** Site-wide identity. */
export const SITE = {
  title: "Trend Content Engine",
  tagline: "One grounded article a day, built from what the internet is actually talking about.",
  description:
    "A daily, AI-assisted digest of what's trending across Hacker News, arXiv, GitHub and Reddit — clustered by topic, scored, and written from cited sources only.",
  author: "Trend Content Engine",
  language: "en",
} as const;

export type Post = CollectionEntry<"posts">;

/** Canonical post path (always no trailing slash). */
export function postPath(slug: string): string {
  return `/posts/${slug}`;
}

/** Absolute URL for a site-relative path. */
export function absolute(site: URL | undefined, path: string): string {
  const base = site ?? new URL("https://example.com");
  return new URL(path, base).href;
}

/**
 * Public path for a built page. `build.format: 'file'` puts `.html` on
 * `Astro.url.pathname`, but canonicals and share URLs must stay clean
 * (and never gain a trailing slash).
 */
export function cleanPath(pathname: string): string {
  let path = pathname || "/";
  if (path === "/index.html") return "/";
  if (path.endsWith("/index.html")) path = path.slice(0, -"index.html".length);
  if (path.endsWith(".html")) path = path.slice(0, -".html".length);
  return path || "/";
}

export function formatDate(date: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(date);
}

export function formatDateShort(date: Date): string {
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/** Rough reading time from the markdown body. */
export function readingTime(body: string): number {
  const words = body.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 220));
}

/** Newest first, with a stable tie-break so builds are deterministic. */
export function sortPosts(posts: Post[]): Post[] {
  return [...posts].sort((a, b) => {
    const diff = b.data.date.valueOf() - a.data.date.valueOf();
    return diff !== 0 ? diff : a.data.slug.localeCompare(b.data.slug);
  });
}

export function allTags(posts: Post[]): { tag: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const post of posts) {
    for (const tag of post.data.tags) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([tag, count]) => ({ tag, count }))
    .sort((a, b) => (b.count - a.count) || a.tag.localeCompare(b.tag));
}

export function postsWithTag(posts: Post[], tag: string): Post[] {
  return posts.filter((post) => post.data.tags.includes(tag));
}

/** Year → posts, newest year first. */
export function byYear(posts: Post[]): { year: number; posts: Post[] }[] {
  const groups = new Map<number, Post[]>();
  for (const post of posts) {
    const year = post.data.date.getUTCFullYear();
    const bucket = groups.get(year) ?? [];
    bucket.push(post);
    groups.set(year, bucket);
  }
  return [...groups.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([year, items]) => ({ year, posts: items }));
}
