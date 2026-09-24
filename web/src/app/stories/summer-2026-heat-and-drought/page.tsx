import type { Metadata } from "next";
import { SITE_URL } from "@/lib/siteConfig";
import SummerStory from "@/content/stories/summer-2026-heat-and-drought/SummerStory";
import { TITLE } from "@/content/stories/summer-2026-heat-and-drought/meta";

const PATH = "/stories/summer-2026-heat-and-drought";
const DESCRIPTION =
  "Much of the northern hemisphere was hot in summer 2026, and almost all of it still got its normal rain. Western Europe did not. Heat and rainfall, country by country, from the Copernicus ERA5/ERA5T record.";
const SHORT_DESCRIPTION =
  "Heat was everywhere in summer 2026. Only western Europe went without rain. The two measured together, from the Copernicus ERA5/ERA5T record.";
const PUBLISHED = "2026-09-25";
const AUTHORS = ["Benoit Leveau", "Fanny Chaléon"];
const OG_IMAGE = "/story/summer-2026-heat-and-drought-og.png";
const OG_IMAGE_ALT =
  "Two maps of Europe sharing one frame: the left half shows summer 2026 temperature far above normal over France and Iberia, the right half shows rainfall far below normal across the same ground.";

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
    name: "Copernicus ERA5 reanalysis, 2 m air temperature and total precipitation",
    description:
      "Hourly estimates of 2 m air temperature and total precipitation from the ECMWF ERA5/ERA5T global atmospheric reanalysis, distributed through the Copernicus Climate Data Store.",
    creator: {
      "@type": "Organization",
      name: "European Centre for Medium-Range Weather Forecasts",
    },
    license: "https://apps.ecmwf.int/datasets/licences/copernicus/",
  },
};

export default function Summer2026StoryPage() {
  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <SummerStory />
    </>
  );
}
