/**
 * A place name split for a running sentence: "In the North Sea, …".
 *
 * The article comes back apart from the name so it can be typeset with the
 * small words before it ("In the") rather than with the emphasised name.
 *
 * Whether a name takes "the" is decided server-side, where its kind is known
 * (see climate/geo/names.py); this only applies that decision. The bare label
 * is still what to show on its own, as a heading or in search results.
 */
export function sentenceParts(
  label: string,
  definiteArticle: boolean,
): { article: string; name: string } {
  if (!definiteArticle) return { article: "", name: label };
  // "The Netherlands" carries its own article, capitalised for standing alone.
  return { article: "the", name: label.replace(/^the\s+/i, "") };
}
