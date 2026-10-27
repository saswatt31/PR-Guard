import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.resolve(__dirname),
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
