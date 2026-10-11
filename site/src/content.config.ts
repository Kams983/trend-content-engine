import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// Every field is required: a malformed post must fail the build rather than
// render an incomplete page.
const posts = defineCollection({
  loader: glob({ pattern: "**/*.md", base: "./content/posts" }),
  schema: z.object({
    title: z.string().min(1).max(200),
    description: z.string().min(1).max(400),
    date: z.coerce.date(),
    slug: z.string().min(1),
    topic_id: z.number().int().nonnegative(),
    ai_assisted: z.boolean(),
    tags: z.array(z.string().min(1)).default([]),
    sources: z
      .array(
        z.object({
          title: z.string(),
          url: z.string(),
          source: z.string(),
        }),
      )
      .default([]),
  }),
});

export const collections = { posts };
