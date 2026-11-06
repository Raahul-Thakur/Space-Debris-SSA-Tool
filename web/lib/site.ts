/**
 * The site's public address, for anything that must be absolute: social
 * preview images, the sitemap, robots.txt. Baked in at build time like every
 * NEXT_PUBLIC_ value, so a change of domain needs a rebuild.
 */
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://astra-ssa.vercel.app";
