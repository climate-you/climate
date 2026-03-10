import type { Metadata } from "next";
import Script from "next/script";
import { SITE_HOST, SITE_URL } from "@/lib/siteConfig";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: "Your Climate",
  description: "Interactive climate map for exploring local climate trends.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <Script id="goatcounter-host-guard" strategy="beforeInteractive">
          {`
            if (window.location.host !== ${JSON.stringify(SITE_HOST)}) {
              window.goatcounter = { no_onload: true };
            }
          `}
        </Script>
        <Script
          data-goatcounter="https://climate.goatcounter.com/count"
          src="//gc.zgo.at/count.js"
          strategy="afterInteractive"
        />
        {children}
      </body>
    </html>
  );
}
