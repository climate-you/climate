import type { Metadata } from "next";
import { SITE_URL } from "@/lib/siteConfig";
import HeatwaveStory from "@/content/stories/june-2026-heatwave/HeatwaveStory";

const PATH = "/stories/june-2026-heatwave";
const TITLE = "The June 2026 heatwave over Europe";
const DESCRIPTION =
  "Two spells of extreme heat swept Europe between mid-June and mid-July 2026. Where the heat sat, how it moved, and how far above the seasonal average it was — from the Copernicus ERA5/ERA5T record.";
const SHORT_DESCRIPTION =
  "Two spells of extreme heat swept Europe between mid-June and mid-July 2026, mapped from the Copernicus ERA5/ERA5T record.";
const PUBLISHED = "2026-07-19";
const AUTHORS = ["Benoit Leveau", "Fanny Chaléon"];
const OG_IMAGE = "/story/june-2026-heatwave-og.png";
const OG_IMAGE_ALT =
  "Temperature anomaly over Europe during the June–July 2026 heat, with France and the Low Countries far above the seasonal average.";

export const metadata: Metadata = {
  title: `${TITLE} | Your Climate`,
  description: DESCRIPTION,
  authors: AUTHORS.map((name) => ({ name })),
  alternates: {
    canonical: PATH,
  },
  openGraph: {
    title: TITLE,
    description: SHORT_DESCRIPTION,
    type: "article",
    url: `${SITE_URL}${PATH}`,
    publishedTime: PUBLISHED,
    authors: AUTHORS,
    images: [{ url: OG_IMAGE, width: 1200, height: 630, alt: OG_IMAGE_ALT }],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: SHORT_DESCRIPTION,
    images: [OG_IMAGE],
  },
};

// Structured data so the page is understood as a dated, attributed article
// rather than another app screen, and can surface as a rich result.
const jsonLd = {
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  headline: TITLE,
  description: DESCRIPTION,
  datePublished: PUBLISHED,
  dateModified: PUBLISHED,
  image: [`${SITE_URL}${OG_IMAGE}`],
  author: AUTHORS.map((name) => ({ "@type": "Person", name })),
  publisher: { "@type": "Organization", name: "climate.you" },
  mainEntityOfPage: { "@type": "WebPage", "@id": `${SITE_URL}${PATH}` },
  isBasedOn: {
    "@type": "Dataset",
    name: "Copernicus ERA5 reanalysis, 2 m air temperature",
    description:
      "Hourly estimates of 2 m air temperature from the ECMWF ERA5/ERA5T global atmospheric reanalysis, distributed through the Copernicus Climate Data Store.",
    creator: {
      "@type": "Organization",
      name: "European Centre for Medium-Range Weather Forecasts",
    },
    license: "https://apps.ecmwf.int/datasets/licences/copernicus/",
  },
};

export default function June2026HeatwaveStoryPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <HeatwaveStory />
    </>
  );
}
