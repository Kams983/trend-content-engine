import type { APIContext } from "astro";

/** robots.txt, generated so the sitemap URL always matches SITE_URL. */
export function GET(context: APIContext): Response {
  const origin = context.site ?? new URL("https://example.com");
  const sitemap = new URL("sitemap-index.xml", origin).href;
  const body = ["User-agent: *", "Allow: /", "", `Sitemap: ${sitemap}`, ""].join("\n");
  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
