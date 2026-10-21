import { build } from "esbuild";
await build({ entryPoints: ["eval/category_audit.ts"], bundle: true, platform: "node", format: "esm", outfile: "eval/.out/audit.mjs", packages: "external" });
await import("./.out/audit.mjs");
