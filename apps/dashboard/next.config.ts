import type { NextConfig } from 'next';

// One origin for UI + API: no CORS, no token in the browser.
const API_ORIGIN = process.env.STUDIO_API_ORIGIN ?? 'http://127.0.0.1:8018';

const config: NextConfig = {
  poweredByHeader: false,
  // Keep `next dev` from writing AGENTS.md into apps/dashboard; the architecture
  // rules live in the repo-root AGENTS.md and must not be duplicated.
  agentRules: false,
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${API_ORIGIN}/api/:path*` }];
  },
  async headers() {
    return [{ source: '/:path*', headers: [
      { key: 'X-Content-Type-Options', value: 'nosniff' },
      { key: 'Referrer-Policy', value: 'no-referrer' },
      { key: 'X-Frame-Options', value: 'DENY' },
      { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' }
    ] }];
  }
};
export default config;
