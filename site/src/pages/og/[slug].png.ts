import { getCollection } from "astro:content";

import { renderOgImage } from "../../lib/og";
import { SITE, formatDate, sortPosts } from "../../lib/site";

/** One 1200x630 OG image per post, generated at build time. */
export async function getStaticPaths() {
  const posts = sortPosts(await getCollection("posts"));
  return posts.map((post) => ({
    params: { slug: post.data.slug },
    props: {
      title: post.data.title,
      footer: `${SITE.title} · ${formatDate(post.data.date)}`,
    },
  }));
}

export async function GET({ props }: { props: { title: string; footer: string } }) {
  const png = await renderOgImage({
    title: props.title,
    kicker: "Daily trend digest",
    footer: props.footer,
  });
  return new Response(png, {
    headers: {
      "Content-Type": "image/png",
      "Cache-Control": "public, max-age=31536000, immutable",
    },
  });
}
