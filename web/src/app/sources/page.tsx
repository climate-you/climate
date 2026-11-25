import type { Metadata } from "next";
import { pageTitle, SITE_NAME } from "@/lib/siteIdentity";
import ExplorerPage from "../ExplorerPage";

export const metadata: Metadata = {
  title: pageTitle("Sources"),
  description: `Data sources, references, and licenses used by ${SITE_NAME}.`,
  alternates: {
    canonical: "/sources",
  },
};

export default function SourcesRoutePage() {
  return <ExplorerPage initialOverlay="sources" initialOverlayBasePath="/" />;
}
