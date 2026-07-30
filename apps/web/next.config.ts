import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: process.cwd(),
  async rewrites() {
    return [{ source: "/studio", destination: "/" }];
  },
};
export default nextConfig;
