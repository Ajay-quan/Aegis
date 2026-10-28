import { build } from "esbuild";
import { cpSync, mkdirSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist");
const common = { bundle: true, target: "chrome116", legalComments: "none", logLevel: "warning" };
await build({ ...common, entryPoints: { background: "src/background.ts", offscreen: "src/offscreen/offscreen.ts", app: "src/ui/app.ts", popup: "src/ui/popup.ts" }, format: "esm", outdir: "dist" });
await build({ ...common, entryPoints: ["src/content/content.ts"], format: "iife", outfile: "dist/content.js" });
cpSync("static", "dist", { recursive: true });
mkdirSync("dist/ort");
for (const f of ["ort-wasm-simd-threaded.asyncify.wasm", "ort-wasm-simd-threaded.asyncify.mjs"]) cpSync(`node_modules/onnxruntime-web/dist/${f}`, `dist/ort/${f}`);
console.log("built dist/");
