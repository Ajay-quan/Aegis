import { build } from "esbuild";
await build({ entryPoints: ["eval/longmemeval.ts"], bundle: true, platform: "node", format: "esm", outfile: "eval/.out/longmemeval.mjs",
  packages: "external", target: "node20" });
await import("./.out/longmemeval.mjs");
