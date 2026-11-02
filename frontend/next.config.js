// Static export served by the FastAPI backend at /app (same origin as /api, so cookies just work).
// In `next dev`, /api/* is proxied to the local backend instead. Rewrites are not allowed together
// with `output: 'export'`, so they are only added in development.
const isDev = process.env.NODE_ENV === 'development';

/** @type {import('next').NextConfig} */
module.exports = {
  basePath: '/app',
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  reactStrictMode: true,
  // Don't let `next dev` write AGENTS.md / CLAUDE.md into this folder.
  agentRules: false,
  ...(isDev
    ? {
        // With trailingSlash, Next would first redirect /api/v1/x to /api/v1/x/ (which FastAPI does not
        // route). Skipping that redirect in development lets the rewrite below proxy the exact path.
        skipTrailingSlashRedirect: true,
        async rewrites() {
          return [
            { source: '/api/:path*', destination: 'http://localhost:8000/api/:path*', basePath: false },
          ];
        },
      }
    : { output: 'export' }),
};
