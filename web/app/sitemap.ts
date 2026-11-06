import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// Written once at build time: a static export has no server to answer later.
export const dynamic = "force-static";

/**
 * The pages worth finding from a search. Sign-in and the account page are
 * left out on purpose: neither has anything to show a visitor arriving cold.
 * No lastModified, because the build cannot know when a page's words last
 * changed, and a date that moves on every deploy teaches crawlers to ignore it.
 */
const PATHS = ["/", "/docs", "/pricing", "/privacy", "/terms", "/refunds"];

export default function sitemap(): MetadataRoute.Sitemap {
  return PATHS.map((path) => ({ url: new URL(path, SITE_URL).toString() }));
}
