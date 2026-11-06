// Build the static export Cloudflare Pages serves (into out/).
// A script rather than `NEXT_OUTPUT=export next build` in package.json, so
// the same command works from PowerShell as well as on Cloudflare's builders.
import { spawnSync } from "node:child_process";

const env = { ...process.env, NEXT_OUTPUT: "export" };
for (const [command, args] of [
  ["node", ["scripts/copy-cesium.mjs"]],
  ["npx", ["next", "build"]]
]) {
  const result = spawnSync(command, args, { stdio: "inherit", env, shell: process.platform === "win32" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}
