import type { Plugin } from "vite";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { cpSync, existsSync, createReadStream, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, join, normalize } from "node:path";

const dataDir = resolve(fileURLToPath(new URL(".", import.meta.url)), "../site/data");

/** 資料來源是 repo 內由 scripts/build.py 產生的 site/data：dev 時直接以 /data 提供，build 時複製到 dist/data。 */
function siteData(): Plugin {
  return {
    name: "wanluan-site-data",
    configureServer(server) {
      server.middlewares.use("/data", (req, res, next) => {
        const rel = decodeURIComponent((req.url ?? "/").split("?")[0]);
        const file = normalize(join(dataDir, rel));
        if (!file.startsWith(dataDir) || !existsSync(file) || !statSync(file).isFile()) return next();
        res.setHeader("Content-Type", "application/json; charset=utf-8");
        createReadStream(file).pipe(res);
      });
    },
    closeBundle() {
      if (existsSync(dataDir)) cpSync(dataDir, resolve("dist/data"), { recursive: true });
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [vue(), siteData()],
  resolve: { alias: { "@": resolve(fileURLToPath(new URL(".", import.meta.url)), "src") } },
  build: { chunkSizeWarningLimit: 1200 },
});
