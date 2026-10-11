import type { CollectionEntry } from "astro:content";

/**
 * Public identity of the publication.
 *
 * The *engine* that writes this site is called the Trend Content Engine (TCE).
 * That name belongs to the repository, the code, the `state` branch, logs and
 * the internal docs — never to a reader. No page, feed, meta tag, OG image or
 * 404 may contain it, and `npm run check:brand` fails the build if one does.
 *
 * Everything reader-facing is driven by the two values below, which mirror the
 * Python `BRAND_NAME` / `BRAND_TAGLINE` settings. On a hosting build the
 * matching `PUBLIC_BRAND_NAME` / `PUBLIC_BRAND_TAGLINE` variables override them,
 * so a rebrand is an environment change rather than a code edit. Changing these
 * renames the wordmark, page titles, structured data, RSS and share cards at
 * once.
 */
const FALLBACK_BRAND_NAME = "Upwire";
const FALLBACK_BRAND_TAGLINE = "What's rising in tech and AI, with sources.";

const brandName = (import.meta.env.PUBLIC_BRAND_NAME || FALLBACK_BRAND_NAME).trim();
const brandTagline = (import.meta.env.PUBLIC_BRAND_TAGLINE || FALLBACK_BRAND_TAGLINE).trim();

export const BRAND = {
  name: brandName,
  tagline: brandTagline,
} as const;

export const SITE = {
  /** The wordmark and the only name that may appear in rendered output. */
  title: BRAND.name,
  tagline: BRAND.tagline,
  description:
    "A daily, AI-assisted digest of what's trending across Hacker News, arXiv, GitHub and Reddit — clustered by topic, scored, and written from cited sources only.",
  author: BRAND.name,
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
