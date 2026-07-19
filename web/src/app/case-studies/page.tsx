import type { Metadata } from "next";
import ExplorerPage from "../ExplorerPage";

export const metadata: Metadata = {
  title: "Case studies | Your Climate",
  description:
    "Deep dives into individual climate events, mapped from the Copernicus ERA5 record.",
  alternates: {
    canonical: "/case-studies",
  },
};

export default function CaseStudiesRoutePage() {
  return <ExplorerPage initialOverlay="case-studies" initialOverlayBasePath="/" />;
}
