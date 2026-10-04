// A static export served by the API at / (LLD-4 ID-01). In development `next dev` proxies
// /api to the API on :8000, so the session cookie stays same-origin.
const exportBuild = process.env.NODE_ENV === "production";

/** @type {import('next').NextConfig} */
const config = {
  output: exportBuild ? "export" : undefined,
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  ...(exportBuild
    ? {}
    : {
        async rewrites() {
          return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }];
        },
      }),
};

export default config;
