import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Cache Components (on by default in new Next.js 16 apps) prerenders
  // route handlers and pages at build time unless they're explicitly gated
  // behind Suspense/`use cache`. Everything in this app is live trading
  // data -- the proxy routes must hit the real backend on every request,
  // never be prerendered against whatever happened to be running at build
  // time -- so it's off entirely rather than threaded through per-route.
  cacheComponents: false,
  turbopack: {
    // Next.js otherwise walks up looking for a lockfile and finds one
    // outside this project (a stray package-lock.json in the home
    // directory); pin the root explicitly so it never guesses wrong.
    root: __dirname,
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
