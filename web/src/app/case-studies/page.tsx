import type { Metadata } from "next";
import { pageTitle } from "@/lib/siteIdentity";
import ExplorerPage from "../ExplorerPage";

export const metadata: Metadata = {
  title: pageTitle("Case studies"),
  description:
    "Deep dives into individual climate events, mapped from the Copernicus ERA5 record.",
  alternates: {
    canonical: "/case-studies",
  },
};

export default function CaseStudiesRoutePage() {
  return (
    <ExplorerPage initialOverlay="case-studies" initialOverlayBasePath="/" />
  );
}
