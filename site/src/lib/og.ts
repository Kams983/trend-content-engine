import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import satori from "satori";
import { Resvg } from "@resvg/resvg-js";

import { SITE } from "./site";

/**
 * Build-time 1200x630 Open Graph images with satori (layout) + resvg (raster).
 *
 * The font is a locally instantiated static cut of Work Sans (SIL OFL 1.1, see
 * src/lib/fonts/OFL.txt). It is read from src/ so it is never shipped to the
 * browser.
 */
/**
 * Read a font from src/lib/fonts. During `astro build` this module is bundled
 * into dist/.prerender, so a relative import.meta.url path is wrong — try the
 * project root first, then fall back to the module location (dev server).
 */
function readFont(name: string): Buffer {
  const candidates = [
    path.join(process.cwd(), "src", "lib", "fonts", name),
    fileURLToPath(new URL(`./fonts/${name}`, import.meta.url)),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return fs.readFileSync(candidate);
  }
  throw new Error(`OG font not found: ${name}`);
}

const FONT_REGULAR = readFont("WorkSans-Regular.ttf");
const FONT_SEMIBOLD = readFont("WorkSans-SemiBold.ttf");

const WIDTH = 1200;
const HEIGHT = 630;

type OgOptions = {
  title: string;
  kicker?: string;
  footer?: string;
};

function toArrayBuffer(buffer: Buffer): ArrayBuffer {
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength) as ArrayBuffer;
}

export async function renderOgImage({ title, kicker, footer }: OgOptions): Promise<Uint8Array> {
  const element = {
    type: "div",
    props: {
      style: {
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        width: "100%",
        height: "100%",
        padding: "72px 80px 64px",
        backgroundColor: "#f8f7f4",
        color: "#191a1d",
        fontFamily: "Work Sans",
      },
      children: [
        {
          type: "div",
          props: {
            style: {
              display: "flex",
              flexDirection: "column",
              gap: "28px",
            },
            children: [
              {
                type: "div",
                props: {
                  style: {
                    display: "flex",
                    fontSize: 28,
                    letterSpacing: "0.14em",
                    textTransform: "uppercase",
                    color: "#28566f",
                    fontWeight: 600,
                  },
                  children: kicker ?? SITE.title,
                },
              },
              {
                type: "div",
                props: {
                  style: {
                    display: "flex",
                    fontSize: title.length > 90 ? 56 : 68,
                    lineHeight: 1.12,
                    fontWeight: 600,
                    letterSpacing: "-0.015em",
                    maxWidth: "1000px",
                  },
                  children: title,
                },
              },
            ],
          },
        },
        {
          type: "div",
          props: {
            style: {
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-end",
              fontSize: 26,
              color: "#5d6070",
            },
            children: [
              { type: "div", props: { style: { display: "flex" }, children: footer ?? "" } },
              { type: "div", props: { style: { display: "flex" }, children: "AI-assisted · sources cited" } },
            ],
          },
        },
      ],
    },
  };

  const svg = await satori(element as never, {
    width: WIDTH,
    height: HEIGHT,
    fonts: [
      { name: "Work Sans", data: toArrayBuffer(FONT_REGULAR), weight: 400, style: "normal" },
      { name: "Work Sans", data: toArrayBuffer(FONT_SEMIBOLD), weight: 600, style: "normal" },
    ],
  });

  const rendered = new Resvg(svg, { fitTo: { mode: "width", value: WIDTH } }).render();
  return rendered.asPng();
}
