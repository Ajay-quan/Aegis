// Build and zip dist/ for Chrome Web Store upload.
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
execSync("node build.mjs", { stdio: "inherit" });
const { version } = JSON.parse(readFileSync("dist/manifest.json", "utf8"));
execSync(`rm -f aegismem-${version}.zip && cd dist && zip -qr ../aegismem-${version}.zip .`, { stdio: "inherit" });
console.log(`packaged aegismem-${version}.zip`);
