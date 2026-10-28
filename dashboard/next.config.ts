import path from "node:path";

import type { NextConfig } from "next";

// Accept both "1" (used by the Dockerfile) and "true" (shell-friendly) so the
// image's runner stage always finds .next/standalone.
const standaloneOutput = ["1", "true"].includes(
  (process.env.NEXT_OUTPUT_STANDALONE ?? "").toLowerCase(),
);

const nextConfig: NextConfig = {
  // Docker uses the standalone server. Vercel and the local demo build do not;
  // keeping it opt-in avoids Next's "next start does not work with standalone"
  // warning and lets Vercel use its normal output layout.
  ...(standaloneOutput ? { output: "standalone" as const } : {}),
  outputFileTracingRoot: path.resolve(__dirname),
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
