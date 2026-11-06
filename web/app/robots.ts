import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// Written once at build time: a static export has no server to answer later.
export const dynamic = "force-static";

/**
 * Everything public may be crawled. The account page is per-visitor and
 * empty to a crawler, and /api/ is the public-read proxy, whose JSON is no
 * use in search results and costs an API call per fetch.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/account", "/api/"] },
    sitemap: `${SITE_URL}/sitemap.xml`
  };
}
