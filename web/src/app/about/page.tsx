import type { Metadata } from "next";
import { pageTitle, SITE_NAME } from "@/lib/siteIdentity";
import ExplorerPage from "../ExplorerPage";

export const metadata: Metadata = {
  title: pageTitle("About"),
  description: `About ${SITE_NAME}, its interactive climate globe and the people behind it.`,
  alternates: {
    canonical: "/about",
  },
};

export default function AboutRoutePage() {
  return <ExplorerPage initialOverlay="about" initialOverlayBasePath="/" />;
}
