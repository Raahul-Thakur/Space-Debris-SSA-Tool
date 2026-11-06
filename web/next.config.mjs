/**
 * Two ways to build the same site.
 *
 * Production runs on Cloudflare Pages as a static export (`npm run
 * build:cloudflare`, which sets NEXT_OUTPUT=export): every page is plain
 * HTML and JavaScript served from the CDN, and the one piece of server code,
 * the public API proxy, runs as a Pages Function in functions/.
 *
 * Everything else (`next dev`, `next build`, a Vercel deployment) runs as a
 * Next.js server, where the same proxy is the route handler in
 * app/api/public/[...path]/route.server.ts. A static export cannot contain a
 * route handler, so `.server.ts` files are recognised only when the build
 * is not an export.
 */
const staticExport = process.env.NEXT_OUTPUT === "export";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1"],
  // A static export is written to this directory, and Cloudflare Pages is
  // pointed at `out`.
  distDir: process.env.NEXT_DIST_DIR || (staticExport ? "out" : ".next"),
  env: {
    NEXT_PUBLIC_CESIUM_BASE_URL: "/cesium"
  },
  pageExtensions: staticExport
    ? ["tsx", "ts", "jsx", "js"]
    : ["tsx", "ts", "jsx", "js", "server.ts"],
  ...(staticExport ? { output: "export" } : {})
};

export default nextConfig;
