import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_API = "https://clinevo-api.onrender.com";

function normalize(raw) {
  return (raw || "")
    .trim()
    .replace(/\/$/, "")
    .replace(/\/api(?:\/.*)?$/, "");
}

const fromEnv = normalize(process.env.API_URL || process.env.BACKEND_URL || "");
const api = fromEnv || DEFAULT_API;
const source = fromEnv
  ? process.env.API_URL
    ? "API_URL"
    : "BACKEND_URL"
  : "default (clinevo-api.onrender.com)";

if (!/^https:\/\//.test(api)) {
  console.error("API origin must be https, got:", api);
  process.exit(1);
}

const dest = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "app", "core", "environment.prod.ts");
writeFileSync(
  dest,
  `export const environment = {\n  production: true,\n  apiUrl: ${JSON.stringify(api)},\n};\n`,
);
console.log(`Wrote production apiUrl ${api} (from ${source})`);
