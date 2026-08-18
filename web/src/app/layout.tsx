import type { Metadata } from "next";
import Script from "next/script";
import { ANALYTICS_OPT_OUT_BOOTSTRAP } from "@/lib/analytics/optOut";
import { GOATCOUNTER_ENDPOINT, SITE_HOST, SITE_URL } from "@/lib/siteConfig";
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
    <html lang="en" suppressHydrationWarning>
      <body>
        {/* Must stay ahead of the GoatCounter tags: it writes the `skipgc`
            key those scripts read as they load. */}
        <Script id="analytics-opt-out" strategy="beforeInteractive">
          {ANALYTICS_OPT_OUT_BOOTSTRAP}
        </Script>
        {GOATCOUNTER_ENDPOINT ? (
          <>
            <Script id="goatcounter-host-guard" strategy="beforeInteractive">
              {`
                if (window.location.host !== ${JSON.stringify(SITE_HOST)}) {
                  window.goatcounter = { no_onload: true };
                }
              `}
            </Script>
            <Script
              data-goatcounter={GOATCOUNTER_ENDPOINT}
              src="//gc.zgo.at/count.js"
              strategy="afterInteractive"
            />
          </>
        ) : null}
        {children}
      </body>
    </html>
  );
}
