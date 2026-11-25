// The site's one name, and the structured data that ties it to the domain.
// "climate.you" is the brand as well as the address: every page title, the
// social cards and the publisher on each story use it, so search engines and
// assistants read climate.you as its own site rather than a misspelling of a
// similarly named one.
import { SITE_URL } from "@/lib/siteConfig";

export const SITE_NAME = "climate.you";

export const SITE_DESCRIPTION =
  "climate.you is an interactive globe showing how temperature, rainfall and the sea have changed where you live, from the Copernicus ERA5 climate record.";

const ORGANIZATION_ID = `${SITE_URL}/#organization`;
const WEBSITE_ID = `${SITE_URL}/#website`;

/** Page title suffixed with the site name. */
export const pageTitle = (title: string) => `${title} | ${SITE_NAME}`;

/** Reference to the publisher, for an article's `publisher` field. */
export const PUBLISHER_REF = {
  "@type": "Organization",
  "@id": ORGANIZATION_ID,
  name: SITE_NAME,
  url: `${SITE_URL}/`,
};

/** WebSite and Organization nodes for the home page: Google takes the site
 *  name it shows in results from the WebSite node on the home page. */
export const SITE_JSON_LD = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "WebSite",
      "@id": WEBSITE_ID,
      name: SITE_NAME,
      url: `${SITE_URL}/`,
      description: SITE_DESCRIPTION,
      inLanguage: "en",
      publisher: { "@id": ORGANIZATION_ID },
    },
    {
      "@type": "Organization",
      "@id": ORGANIZATION_ID,
      name: SITE_NAME,
      url: `${SITE_URL}/`,
      logo: `${SITE_URL}/story/logo.png`,
      sameAs: ["https://github.com/climate-you"],
    },
  ],
};
