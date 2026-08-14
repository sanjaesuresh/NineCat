// Copies the pipeline's exported dataset into public/data so Vite serves it
// as a static asset. Runs before dev/build; a missing source (pipeline
// hasn't run yet) is not a build failure -- warn and continue so the
// dashboard can still scaffold/build and show its own empty state at runtime.
import { copyFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "../../data/players_2026_27.json");
const dest = resolve(here, "../public/data/players_2026_27.json");

if (!existsSync(source)) {
  console.warn(
    `[sync-data] ${source} not found -- run the projections pipeline first. Skipping copy.`,
  );
  process.exit(0);
}

await mkdir(dirname(dest), { recursive: true });
await copyFile(source, dest);
console.log(`[sync-data] copied ${source} -> ${dest}`);
