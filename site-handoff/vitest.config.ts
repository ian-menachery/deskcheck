// Mirrors the site's vitest.config.ts with site/ as the root, so the files under
// site/ drop into the portfolio repo unchanged.
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL("./site", import.meta.url)) } },
  test: { include: ["site/lib/**/*.test.ts"], environment: "node" },
});
