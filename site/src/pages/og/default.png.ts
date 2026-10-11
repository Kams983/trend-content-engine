import { renderOgImage } from "../../lib/og";
import { SITE } from "../../lib/site";

/** Fallback social card for the home, archive, tag and about pages. */
export async function GET() {
  const png = await renderOgImage({
    title: SITE.tagline,
    kicker: SITE.title,
    footer: "hackernews · arxiv · github · reddit",
  });
  return new Response(png, {
    headers: {
      "Content-Type": "image/png",
      "Cache-Control": "public, max-age=31536000, immutable",
    },
  });
}
