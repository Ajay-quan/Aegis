import { build } from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist");
await build({
  entryPoints: { background: "src/background.ts", content: "src/content/content.ts", panel: "src/sidepanel/panel.ts", offscreen: "src/offscreen/offscreen.ts" },
  bundle: true,
  format: "esm",
  target: "chrome116",
  outdir: "dist",
  sourcemap: false,
  minify: false,
  legalComments: "none",
});
// Content scripts are classic scripts: rebuild that one as an IIFE.
await build({ entryPoints: ["src/content/content.ts"], bundle: true, format: "iife", target: "chrome116", outfile: "dist/content.js" });
cpSync("static", "dist", { recursive: true });
// ONNX Runtime Web: bundle the WASM runtime locally (MV3 forbids remote code).
mkdirSync("dist/ort");
for (const f of ["ort-wasm-simd-threaded.asyncify.wasm", "ort-wasm-simd-threaded.asyncify.mjs"]) {
  cpSync(`node_modules/onnxruntime-web/dist/${f}`, `dist/ort/${f}`);
}
console.log("built dist/");
