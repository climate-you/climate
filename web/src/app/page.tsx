import type { Metadata } from "next";
import { SITE_URL } from "@/lib/siteConfig";
import { SITE_DESCRIPTION, SITE_JSON_LD, SITE_NAME } from "@/lib/siteIdentity";
import ExplorerPage from "./ExplorerPage";

// Under ~60 characters, so search results show it whole.
const TITLE = `${SITE_NAME}: visualising local and global climate change`;
// Built with scripts/make_story_og_image.py --image (usage in its docstring).
const OG_IMAGE = "/og/home-og.png";
const OG_IMAGE_ALT =
  "The climate.you globe coloured by how much each place has warmed, beside the global panel charting annual air temperature and hot days since 1979.";

export const metadata: Metadata = {
  title: TITLE,
  description: SITE_DESCRIPTION,
  alternates: {
    canonical: "/",
  },
  openGraph: {
    siteName: SITE_NAME,
    type: "website",
    title: TITLE,
    description: SITE_DESCRIPTION,
    url: `${SITE_URL}/`,
    images: [{ url: OG_IMAGE, width: 1200, height: 630, alt: OG_IMAGE_ALT }],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: SITE_DESCRIPTION,
    images: [OG_IMAGE],
  },
};

export default function HomePage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(SITE_JSON_LD) }}
      />
      <ExplorerPage coldOpen />
    </>
  );
}
