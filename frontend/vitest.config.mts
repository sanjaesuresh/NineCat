import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // no DOM needed: api.ts only calls fetch, node env keeps tests fast
    environment: "node",
    include: ["**/*.test.ts"],
    coverage: {
      provider: "v8",
    },
  },
});
