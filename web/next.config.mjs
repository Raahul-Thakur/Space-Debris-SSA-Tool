/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["127.0.0.1"],
  distDir: process.env.NEXT_DIST_DIR || ".next",
  output: "standalone",
  env: {
    NEXT_PUBLIC_CESIUM_BASE_URL: "/cesium"
  }
};

export default nextConfig;
