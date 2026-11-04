import { build } from "esbuild";
await build({ entryPoints: ["eval/conversations.ts"], bundle: true, platform: "node", format: "esm", outfile: "eval/.out/conversations.mjs", packages: "external", target: "node20", logLevel: "warning" });
await import("./.out/conversations.mjs");
