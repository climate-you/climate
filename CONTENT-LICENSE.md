# Editorial content licence

The **software** in this repository is licensed under the GNU Affero General
Public License v3.0 — see [`LICENSE`](LICENSE).

The **editorial content** is not. Articles and case studies — their text,
headlines, captions, figures, and the editorial selection and annotation of the
data they present — are journalistic work, and are excluded from the AGPL grant.

© 2026 Benoit Leveau & Fanny Chaléon. All rights reserved.

## What is excluded

These paths contain editorial content and are **not** covered by the AGPL:

| Path                        | Contents                                                     |
| --------------------------- | ------------------------------------------------------------ |
| `web/src/app/stories/**`    | Story routes and their page metadata (titles, descriptions)   |
| `web/src/content/stories/**` | Story text, figures, editorial data series and annotations   |

Also excluded, wherever they appear:

- the article text, headlines, and captions published at <https://climate.you>;
- images exported from those articles, including the attributed PNG exports
  produced by the download buttons;
- the `climate.you` name and wordmark, and the logo
  (`web/public/story/logo.png`, `web/src/app/favicon.ico`).

## What this means

You may not copy, republish, translate, or redistribute the editorial content,
in whole or in part, without prior written permission — whether or not you
comply with the AGPL.

Ordinary quotation for press, commentary, and academic work is welcome: quote
briefly, with attribution and a link to the original article. Nothing here
limits any use permitted under applicable copyright exceptions (fair dealing,
fair use, quotation rights, and similar).

## What is *not* excluded

Everything else is AGPL-3.0, exactly like the rest of the codebase — including
the machinery that makes story pages work:

| Path                          | Contents                                              |
| ----------------------------- | ----------------------------------------------------- |
| `web/src/components/story/**` | Reusable story components (maps, globe, panels)        |
| `web/src/lib/story/**`        | Projection maths and image-export helpers              |
| `web/public/story/europe-lines.json` | Coastline/border geometry derived from Natural Earth |

Running your own instance of this software — including the interactive globe,
the map rendering, and the story components — is explicitly welcome under the
AGPL. The intent of this carve-out is narrow: the tools are shared, the
journalism is ours.

Natural Earth source data is public domain; see
[`web/public/THIRD_PARTY_NOTICES.md`](web/public/THIRD_PARTY_NOTICES.md) for
third-party terms.

## Permissions

To request permission to republish or translate editorial content, get in touch
via <https://climate.you>.
