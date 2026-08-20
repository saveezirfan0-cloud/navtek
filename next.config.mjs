/** @type {import('next').NextConfig} */
const nextConfig = {
  // The Python API lives in /api at the root and handles everything under
  // /api/py/*. This rewrite points that whole prefix at the single FastAPI
  // function.
  //
  // Note for anyone extending this: do NOT add route handlers under app/api.
  // Once a project has Python functions in root /api, Vercel routes the /api
  // prefix to them and app/api handlers stop resolving. Use server components
  // and server actions instead — that is why lib/api.ts is server-only.
  rewrites: async () => [
    { source: "/api/py/:path*", destination: "/api/index" },
  ],
  async headers() {
    return [
      { source: "/j/(.*)", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] },
      { source: "/setup", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] },
    ];
  },
};

export default nextConfig;
