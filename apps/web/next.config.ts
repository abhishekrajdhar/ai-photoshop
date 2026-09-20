import type { NextConfig } from "next";

const internalApi = process.env.INTERNAL_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  reactStrictMode: true,
  // Compression buffers Server-Sent Events through the /api proxy; terminate TLS/compression at the edge instead.
  compress: false,
  // Proxy all /api/* calls to the backend so cookies stay same-origin (no CORS, CSRF via header).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${internalApi}/api/:path*` }];
  },
  experimental: {
    // Large uploads are streamed in chunks; the proxy must not buffer them in memory.
    proxyTimeout: 600_000,
  },
};

export default nextConfig;
