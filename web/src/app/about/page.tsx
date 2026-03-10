import type { Metadata } from "next";
import ExplorerPage from "../ExplorerPage";

export const metadata: Metadata = {
  title: "About | Your Climate",
  description: "About the Your Climate interactive map and mission.",
  alternates: {
    canonical: "/about",
  },
};

export default function AboutRoutePage() {
  return (
    <ExplorerPage
      coldOpen
      initialOverlay="about"
      initialOverlayBasePath="/"
    />
  );
}
