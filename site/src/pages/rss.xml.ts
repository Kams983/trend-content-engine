import rss from "@astrojs/rss";
import { experimental_AstroContainer as AstroContainer } from "astro/container";
import { getCollection, render } from "astro:content";
import type { APIContext } from "astro";

import { SITE, absolute, postPath, sortPosts } from "../lib/site";

/** Full-content feed at /rss.xml. */
export async function GET(context: APIContext) {
  const origin = context.site ?? new URL("https://example.com");
  const posts = sortPosts(await getCollection("posts"));
  const container = await AstroContainer.create();

  const items = [];
  for (const post of posts) {
    // Render the markdown to HTML so the feed carries the whole article.
    const { Content } = await render(post);
    const html = await container.renderToString(Content);

    items.push({
      title: post.data.title,
      description: post.data.description,
      pubDate: post.data.date,
      // Absolute so @astrojs/rss does not append a trailing slash.
      link: absolute(origin, postPath(post.data.slug)),
      categories: post.data.tags,
      content: html,
      customData: `<source>${absolute(origin, `/og/${post.data.slug}.png`)}</source>`,
    });
  }

  return rss({
    title: SITE.title,
    description: SITE.description,
    site: origin,
    items,
    customData: `<language>${SITE.language}</language><ttl>60</ttl>`,
  });
}
