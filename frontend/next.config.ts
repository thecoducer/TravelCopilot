import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // OrbStack exposes the dev server through this hostname in the browser.
  allowedDevOrigins: ["frontend.travelcopilot.orb.local"],
  // Pin the project root explicitly: a package-lock.json exists above the git
  // repo root, which otherwise confuses Turbopack's workspace-root inference.
  turbopack: {
    root: path.resolve(import.meta.dirname),
  },
};

export default nextConfig;
