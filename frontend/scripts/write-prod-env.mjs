import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const api = (process.env.API_URL || "").trim().replace(/\/$/, "");
if (!api) {
  console.error(
    "Set API_URL to your Render origin, for example https://clinevo-api.onrender.com",
  );
  process.exit(1);
}
if (!/^https:\/\//.test(api)) {
  console.error("API_URL must be an https origin with no path.");
  process.exit(1);
}

const dest = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "app", "core", "environment.prod.ts");
writeFileSync(
  dest,
  `export const environment = {\n  production: true,\n  apiUrl: ${JSON.stringify(api)},\n};\n`,
);
console.log(`Wrote production apiUrl ${api}`);
