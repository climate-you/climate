import type { Metadata } from "next";
import ExplorerPage from "../ExplorerPage";

export const metadata: Metadata = {
  title: "Sources | Your Climate",
  description: "Data sources, references, and licenses used by Your Climate.",
  alternates: {
    canonical: "/sources",
  },
};

export default function SourcesRoutePage() {
  return (
    <ExplorerPage
      coldOpen
      initialOverlay="sources"
      initialOverlayBasePath="/"
    />
  );
}
