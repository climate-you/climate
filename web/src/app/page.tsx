import type { Metadata } from "next";
import ExplorerPage from "./ExplorerPage";

export const metadata: Metadata = {
  alternates: {
    canonical: "/",
  },
};

export default function HomePage() {
  return <ExplorerPage coldOpen />;
}
