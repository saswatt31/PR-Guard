import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker uses the standalone server. Vercel and the local demo build do not;
  // keeping it opt-in avoids Next's "next start does not work with standalone"
  // warning and lets Vercel use its normal output layout.
  ...(process.env.NEXT_OUTPUT_STANDALONE === "true"
    ? { output: "standalone" as const }
    : {}),
  outputFileTracingRoot: path.resolve(__dirname),
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
