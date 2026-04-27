import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  // Static export for production — output lands in web/out,
  // served by the Python MCP server at /app
  output: isProd ? "export" : undefined,
  basePath: "/health-app",
  assetPrefix: isProd ? "/health-app" : undefined,

};

export default nextConfig;
