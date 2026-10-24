import type { NextConfig } from 'next';

const config: NextConfig = {
  poweredByHeader: false,
  // Keep `next dev` from writing AGENTS.md into apps/dashboard; the architecture
  // rules live in the repo-root AGENTS.md and must not be duplicated.
  agentRules: false,
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
