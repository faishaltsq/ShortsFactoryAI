import type { NextConfig } from "next";

const API_ORIGIN = process.env.STUDIO_API_ORIGIN ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  // Jangan biarkan `next dev` menulis AGENTS.md ke dalam apps/dashboard: aturan
  // arsitektur repo ada di AGENTS.md root dan tidak boleh diduplikasi.
  agentRules: false,
  // Satu origin untuk UI + API: tidak ada CORS, tidak ada token bocor ke browser.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }];
  },
};

export default nextConfig;
