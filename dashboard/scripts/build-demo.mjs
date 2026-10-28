import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const nextBin = path.join(here, "..", "node_modules", "next", "dist", "bin", "next");

// Build with the demo flag inlined. The API URL deliberately points at a closed
// port: if any page still tries to reach a backend, the demo build will fail its
// Playwright journey instead of silently using localhost.
const result = spawnSync(process.execPath, [nextBin, "build"], {
  stdio: "inherit",
  env: {
    ...process.env,
    NEXT_PUBLIC_DEMO_MODE: "true",
    PRGUARD_API_URL: "http://127.0.0.1:9",
  },
});

process.exit(result.status ?? 1);
