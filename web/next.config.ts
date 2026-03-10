import type { NextConfig } from "next";

const extraAllowedDevOrigins = (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((v) => v.trim())
  .filter(Boolean);

const nextConfig: NextConfig = {
  // Allow loading Next dev assets when accessing dev server from LAN devices.
  // Match your DHCP pool on this subnet; add more via NEXT_ALLOWED_DEV_ORIGINS.
  // Examples: "192.168.100.*" or "10.0.0.*,192.168.1.*"
  allowedDevOrigins: [
    "localhost",
    "127.0.0.1",
    "192.168.100.*",
    ...extraAllowedDevOrigins,
  ],
};

export default nextConfig;
