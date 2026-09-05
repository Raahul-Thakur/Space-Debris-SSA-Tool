import { cp, mkdir } from "node:fs/promises";
import { join } from "node:path";

const source = join(process.cwd(), "node_modules", "cesium", "Build", "Cesium");
const destination = join(process.cwd(), "public", "cesium");
await mkdir(destination, { recursive: true });
await cp(source, destination, { recursive: true, force: true });
