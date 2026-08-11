import type { NextConfig } from "next";

// backend runs separately (FastAPI on :8000 in dev); rewriting through this origin
// keeps the session cookie first-party instead of needing cross-site cookie config.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendUrl}/api/:path*` },
      // OAuth callback (/auth/yahoo/callback) lives outside /api, proxy it too
      { source: "/auth/:path*", destination: `${backendUrl}/auth/:path*` },
    ];
  },
};

export default nextConfig;
