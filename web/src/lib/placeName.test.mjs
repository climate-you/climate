import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { sentenceParts } from "./explorer/placeName.ts";

const explorerPageSource = readFileSync(
  resolve("src/app/ExplorerPage.tsx"),
  "utf8",
);

test("a name that takes an article gets one, apart from the name", () => {
  assert.deepEqual(sentenceParts("North Sea", true), {
    article: "the",
    name: "North Sea",
  });
  assert.deepEqual(sentenceParts("United Kingdom", true), {
    article: "the",
    name: "United Kingdom",
  });
});

test("a name that does not is left alone", () => {
  assert.deepEqual(sentenceParts("France", false), {
    article: "",
    name: "France",
  });
  assert.deepEqual(sentenceParts("Lyon, France", false), {
    article: "",
    name: "Lyon, France",
  });
});

test("a name that already carries one has it lifted out, not doubled", () => {
  assert.deepEqual(sentenceParts("The Netherlands", true), {
    article: "the",
    name: "Netherlands",
  });
});

test("a water label with a nearby city appended keeps the city intact", () => {
  assert.deepEqual(
    sentenceParts("North Sea off Aberdeen, United Kingdom", true),
    { article: "the", name: "North Sea off Aberdeen, United Kingdom" },
  );
});

test("the article is set with the small words, not with the emphasised name", () => {
  // Each mid-sentence name follows a small span that carries the article —
  // "In the" — so "the" is never typeset at the size of "United Kingdom".
  const sentenceUses = [
    ...explorerPageSource.matchAll(
      /<span className=\{styles\.panelTitleSmall\}>\s*\{withArticle\("[^"]+"\)\}\s*<\/span>\{" "\}\s*\{sentenceLocationName\}/g,
    ),
  ];
  const allNameUses =
    explorerPageSource.match(/\{sentenceLocationName\}/g) ?? [];
  assert.ok(
    sentenceUses.length >= 8,
    `expected 8 uses, got ${sentenceUses.length}`,
  );
  assert.equal(sentenceUses.length, allNameUses.length);
  // The one place the name stands alone, as a heading, keeps it bare.
  assert.equal(
    (explorerPageSource.match(/\{titleLocationLabel\}/g) ?? []).length,
    1,
  );
});
