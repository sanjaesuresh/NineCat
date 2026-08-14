import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // mirrors tsconfig's "@/*" path alias -- without it any module under
  // components/ that imports a sibling through the alias (which is the house
  // convention) cannot be unit-tested at all, only typechecked
  resolve: {
    alias: {
      "@": path.dirname(fileURLToPath(import.meta.url)),
    },
  },
  test: {
    // no DOM needed: api.ts only calls fetch, node env keeps tests fast
    environment: "node",
    include: ["**/*.test.ts"],
    coverage: {
      provider: "v8",
    },
  },
});
