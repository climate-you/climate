import type { Metadata } from "next";
import HeatwaveStory from "@/content/stories/june-2026-heatwave/HeatwaveStory";

export const metadata: Metadata = {
  title: "The June–July 2026 heat over Europe | Your Climate",
  description:
    "Two spells of extreme heat swept Europe between mid-June and mid-July 2026. Where the heat sat, how it moved, and how far above the seasonal average it was — from the Copernicus ERA5 record.",
  alternates: {
    canonical: "/stories/june-2026-heatwave",
  },
  openGraph: {
    title: "The June–July 2026 heat over Europe",
    description:
      "Two spells of extreme heat swept Europe between mid-June and mid-July 2026, mapped from the Copernicus ERA5 record.",
    type: "article",
  },
};

export default function June2026HeatwaveStoryPage() {
  return <HeatwaveStory />;
}
