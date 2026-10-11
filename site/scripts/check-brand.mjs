/**
 * Build guardrail: the engine name must never reach a reader.
 *
 * The site is produced by the Trend Content Engine (TCE), but readers only ever
 * see the publication brand (`PUBLIC_BRAND_NAME`, defaulting to the value in
 * `src/lib/site.ts`). This script runs as part of `npm run build`, so a stray
 * engine name in a page, feed, sitemap, meta tag or 404 fails the build instead
 * of shipping.
 *
 * Run it directly with `npm run check:brand` (it needs a `dist/` from a build).
 */
import fs from "node:fs";
import path from "node:path";

const dist = path.resolve(process.cwd(), "dist");
const brand = (process.env.PUBLIC_BRAND_NAME || "Upwire").trim();

/** Internal names that must not appear in any built public artifact. */
const FORBIDDEN = [
  { label: "engine name", pattern: /Trend\s+Content\s+Engine/i },
  { label: "engine acronym", pattern: /\bTCE\b/ },
  { label: "engine repo slug", pattern: /trend-content-engine/i },
];

/** Text artifacts worth scanning; binary files are skipped. */
const TEXT_EXTENSIONS = new Set([".html", ".xml", ".txt", ".json", ".js", ".css", ".svg", ".webmanifest"]);

function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else out.push(full);
  }
  return out;
}

if (!fs.existsSync(dist)) {
  console.error(`check:brand — no dist/ to scan (run the build first)`);
  process.exit(1);
}

const files = walk(dist).filter((file) => TEXT_EXTENSIONS.has(path.extname(file).toLowerCase()));
const violations = [];

for (const file of files) {
  const text = fs.readFileSync(file, "utf8");
  const lines = text.split(/\r?\n/);
  for (const { label, pattern } of FORBIDDEN) {
    lines.forEach((line, index) => {
      if (pattern.test(line)) {
        violations.push(`${path.relative(dist, file)}:${index + 1} — ${label}: ${line.trim().slice(0, 120)}`);
      }
    });
  }
}

const home = path.join(dist, "index.html");
if (!fs.existsSync(home)) {
  console.error("check:brand — dist/index.html is missing; the build did not complete");
  process.exit(1);
}
const homeHtml = fs.readFileSync(home, "utf8");
if (!homeHtml.includes(brand)) {
  violations.push(`index.html — the publication brand ${JSON.stringify(brand)} is missing from the home page`);
}

if (violations.length > 0) {
  console.error(`check:brand — ${violations.length} problem(s):`);
  for (const line of violations) console.error(`  ${line}`);
  console.error(
    "\nReader-facing output is brand-driven: set PUBLIC_BRAND_NAME / PUBLIC_BRAND_TAGLINE\n" +
      "(defaults live in src/lib/site.ts) instead of naming the engine.",
  );
  process.exit(1);
}

console.log(`check:brand — ${files.length} built files clean; publication brand is ${JSON.stringify(brand)}`);
