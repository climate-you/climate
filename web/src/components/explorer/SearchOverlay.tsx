"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import styles from "./SearchOverlay.module.css";

export type AutocompleteItem = {
  geonameid: number;
  label: string;
  lat: number;
  lon: number;
  country_code: string;
  population: number;
};

type AutocompleteResponse = {
  results: AutocompleteItem[];
};

type ResolveLocationResponse = {
  result?: AutocompleteItem | null;
};

type SearchOverlayProps = {
  apiBase: string;
  releaseForSession: string;
  onLocationSelect: (item: AutocompleteItem) => void;
  externalError?: string | null;
  className?: string;
};

export default function SearchOverlay({
  apiBase,
  releaseForSession,
  onLocationSelect,
  externalError,
  className,
}: SearchOverlayProps) {
  const [search, setSearch] = useState<string>("");
  const [suggestions, setSuggestions] = useState<AutocompleteItem[]>([]);
  const [suggestOpen, setSuggestOpen] = useState<boolean>(false);
  const [suggestIndex, setSuggestIndex] = useState<number>(-1);
  const [suggestLoading, setSuggestLoading] = useState<boolean>(false);
  const [internalError, setInternalError] = useState<string | null>(null);
  const debounceRef = useRef<number | null>(null);
  const searchWrapRef = useRef<HTMLDivElement | null>(null);

  const fetchAutocomplete = useCallback(
    async (q: string) => {
      const url = `${apiBase}/api/v/${encodeURIComponent(releaseForSession)}/locations/autocomplete?q=${encodeURIComponent(
        q,
      )}&limit=8`;
      const r = await fetch(url);
      if (!r.ok) throw new Error(await r.text());
      const data = (await r.json()) as AutocompleteResponse;
      return data.results ?? [];
    },
    [apiBase, releaseForSession],
  );

  async function resolveByLabel(label: string) {
    const url = `${apiBase}/api/v/${encodeURIComponent(releaseForSession)}/locations/resolve?label=${encodeURIComponent(label)}`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(await r.text());
    const data = (await r.json()) as ResolveLocationResponse;
    return data.result ?? null;
  }

  function applyLocation(item: AutocompleteItem) {
    setSearch("");
    setSuggestOpen(false);
    onLocationSelect(item);
  }

  useEffect(() => {
    if (debounceRef.current) {
      window.clearTimeout(debounceRef.current);
    }
    if (search.trim().length < 3) {
      setSuggestions([]);
      setSuggestOpen(false);
      setSuggestIndex(-1);
      setSuggestLoading(false);
      setInternalError(null);
      return;
    }

    setSuggestLoading(true);
    setInternalError(null);
    debounceRef.current = window.setTimeout(async () => {
      try {
        const results = await fetchAutocomplete(search.trim());
        setSuggestions(results);
        setSuggestOpen(true);
        setSuggestIndex(results.length ? 0 : -1);
      } catch (err: unknown) {
        setInternalError(
          err instanceof Error ? err.message : "Autocomplete failed",
        );
        setSuggestions([]);
        setSuggestOpen(false);
        setSuggestIndex(-1);
      } finally {
        setSuggestLoading(false);
      }
    }, 250);
  }, [fetchAutocomplete, search]);

  useEffect(() => {
    if (!suggestOpen) return;
    const closeIfOutside = (target: EventTarget | null) => {
      if (!searchWrapRef.current) return;
      if (!(target instanceof Node)) return;
      if (searchWrapRef.current.contains(target)) return;
      setSuggestOpen(false);
      setSuggestIndex(-1);
    };
    const onWindowPointerDown = (event: PointerEvent) => {
      closeIfOutside(event.target);
    };
    const onWindowFocusIn = (event: FocusEvent) => {
      closeIfOutside(event.target);
    };
    const onWindowWheel = (event: WheelEvent) => {
      closeIfOutside(event.target);
    };
    window.addEventListener("pointerdown", onWindowPointerDown, true);
    window.addEventListener("focusin", onWindowFocusIn, true);
    window.addEventListener("wheel", onWindowWheel, true);
    return () => {
      window.removeEventListener("pointerdown", onWindowPointerDown, true);
      window.removeEventListener("focusin", onWindowFocusIn, true);
      window.removeEventListener("wheel", onWindowWheel, true);
    };
  }, [suggestOpen]);

  const displayError = internalError ?? externalError ?? null;

  return (
    <div className={className}>
      <div ref={searchWrapRef} className={styles.searchWrap}>
        <input
          className={styles.searchInput}
          placeholder="Type a city name..."
          suppressHydrationWarning
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onFocus={() => {
            if (suggestions.length) setSuggestOpen(true);
          }}
          onKeyDown={async (e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setSuggestIndex((i) => Math.min(i + 1, suggestions.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setSuggestIndex((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              if (suggestIndex >= 0 && suggestions[suggestIndex]) {
                applyLocation(suggestions[suggestIndex]);
                return;
              }
              if (search.trim().length >= 3) {
                const hit = await resolveByLabel(search.trim());
                if (hit) {
                  applyLocation(hit);
                }
                setSuggestOpen(false);
              }
            } else if (e.key === "Escape") {
              setSuggestOpen(false);
            }
          }}
        />
        {suggestOpen && suggestions.length > 0 ? (
          <div className={styles.suggestionList}>
            {suggestions.map((s, i) => (
              <div
                key={`${s.geonameid}:${s.label}`}
                onMouseDown={(evt) => {
                  evt.preventDefault();
                  applyLocation(s);
                }}
                onMouseEnter={() => setSuggestIndex(i)}
                className={`${styles.suggestionItem} ${
                  i === suggestIndex ? styles.suggestionItemActive : ""
                }`}
              >
                {s.label}
              </div>
            ))}
          </div>
        ) : null}
      </div>
      {suggestLoading ? (
        <div className={styles.searchStatus}>Searching...</div>
      ) : null}
      {displayError ? (
        <div className={styles.searchError}>{displayError}</div>
      ) : null}
    </div>
  );
}
