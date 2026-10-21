import type { NextConfig } from "next";

const API_ORIGIN = process.env.STUDIO_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Satu origin untuk UI + API: tidak ada CORS, tidak ada token bocor ke browser.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
