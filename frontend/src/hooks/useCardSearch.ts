import { useEffect, useRef, useState } from "react";
import type {
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
} from "react";

import { listCardPrintings, searchCardNames } from "../api";
import {
  createSearchCardGroups,
  type SearchCardGroup,
} from "../searchResultHelpers";
import type { CatalogNameSearchRow, CatalogSearchRow } from "../types";
import { toUserMessage } from "../uiHelpers";
import type { AsyncStatus } from "../uiTypes";

const AUTOCOMPLETE_MIN_QUERY_LENGTH = 2;
const AUTOCOMPLETE_DEBOUNCE_MS = 250;
const AUTOCOMPLETE_LIMIT = 5;
const SEARCH_GROUP_LIMIT = 8;

type UseCardSearchOptions = {
  onSearchActivity?: () => void;
};

export function useCardSearch(options: UseCardSearchOptions = {}) {
  const [searchStatus, setSearchStatus] = useState<AsyncStatus>("idle");
  const [suggestionStatus, setSuggestionStatus] = useState<AsyncStatus>("idle");
  const [searchError, setSearchError] = useState<string | null>(null);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<CatalogNameSearchRow[]>([]);
  const [suggestionResults, setSuggestionResults] = useState<CatalogNameSearchRow[]>([]);
  const [suggestionOpen, setSuggestionOpen] = useState(false);
  const [highlightedSuggestionIndex, setHighlightedSuggestionIndex] = useState(-1);
  const suggestionLookupRequestIdRef = useRef(0);
  const suggestionCacheRef = useRef<Record<string, CatalogNameSearchRow[]>>({});
  const printingLookupCacheRef = useRef<Record<string, CatalogSearchRow[]>>({});
  const printingLookupPromisesRef = useRef<Record<string, Promise<CatalogSearchRow[]>>>({});
  const skipSuggestionFetchQueryRef = useRef<string | null>(null);

  useEffect(() => {
    const trimmed = searchQuery.trim();
    const normalizedQuery = trimmed.toLowerCase();

    if (skipSuggestionFetchQueryRef.current === normalizedQuery) {
      skipSuggestionFetchQueryRef.current = null;
      return;
    }

    if (trimmed.length < AUTOCOMPLETE_MIN_QUERY_LENGTH) {
      suggestionLookupRequestIdRef.current += 1;
      setSuggestionStatus("idle");
      setSuggestionError(null);
      setSuggestionResults([]);
      setSuggestionOpen(false);
      setHighlightedSuggestionIndex(-1);
      return;
    }

    const cachedResults = suggestionCacheRef.current[normalizedQuery];
    if (cachedResults) {
      setSuggestionStatus("ready");
      setSuggestionError(null);
      setSuggestionResults(cachedResults);
      setHighlightedSuggestionIndex(cachedResults.length ? 0 : -1);
      return;
    }

    const requestId = ++suggestionLookupRequestIdRef.current;
    const timeoutId = window.setTimeout(() => {
      setSuggestionStatus("loading");
      setSuggestionError(null);

      void searchCardNames({
        query: trimmed,
        limit: AUTOCOMPLETE_LIMIT,
      })
        .then((results) => {
          if (requestId !== suggestionLookupRequestIdRef.current) {
            return;
          }
          suggestionCacheRef.current[normalizedQuery] = results;
          setSuggestionResults(results);
          setSuggestionStatus("ready");
          setHighlightedSuggestionIndex(results.length ? 0 : -1);
        })
        .catch((error) => {
          if (requestId !== suggestionLookupRequestIdRef.current) {
            return;
          }
          setSuggestionResults([]);
          setSuggestionError(toUserMessage(error, "Suggestions could not load."));
          setSuggestionStatus("error");
          setHighlightedSuggestionIndex(-1);
        });
    }, AUTOCOMPLETE_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [searchQuery]);

  function closeSuggestionList() {
    setSuggestionOpen(false);
    setHighlightedSuggestionIndex(-1);
  }

  function resetSearchWorkspace() {
    suggestionLookupRequestIdRef.current += 1;
    skipSuggestionFetchQueryRef.current = null;
    setSearchQuery("");
    setSearchResults([]);
    setSearchStatus("idle");
    setSearchError(null);
    setSuggestionStatus("idle");
    setSuggestionError(null);
    setSuggestionResults([]);
    closeSuggestionList();
  }

  function openSuggestionList() {
    if (searchQuery.trim().length < AUTOCOMPLETE_MIN_QUERY_LENGTH) {
      return;
    }

    setSuggestionOpen(true);
    setHighlightedSuggestionIndex((current) => {
      if (current >= 0 && current < suggestionResults.length) {
        return current;
      }
      return suggestionResults.length ? 0 : -1;
    });
  }

  function moveSuggestionHighlight(direction: 1 | -1) {
    if (searchQuery.trim().length < AUTOCOMPLETE_MIN_QUERY_LENGTH) {
      return;
    }

    setSuggestionOpen(true);
    setHighlightedSuggestionIndex((current) => {
      if (!suggestionResults.length) {
        return -1;
      }
      if (current === -1) {
        return direction > 0 ? 0 : suggestionResults.length - 1;
      }

      const nextIndex = current + direction;
      if (nextIndex < 0) {
        return suggestionResults.length - 1;
      }
      if (nextIndex >= suggestionResults.length) {
        return 0;
      }
      return nextIndex;
    });
  }

  async function runCardSearch(query: string) {
    const trimmed = query.trim();
    if (!trimmed) {
      setSearchResults([]);
      setSearchStatus("idle");
      setSearchError(null);
      return;
    }

    options.onSearchActivity?.();
    suggestionLookupRequestIdRef.current += 1;
    closeSuggestionList();

    setSearchStatus("loading");
    setSearchError(null);

    try {
      const results = await searchCardNames({
        query: trimmed,
        limit: SEARCH_GROUP_LIMIT,
      });
      setSearchResults(results);
      setSearchStatus("ready");
    } catch (error) {
      setSearchResults([]);
      setSearchError(toUserMessage(error, "Card search failed."));
      setSearchStatus("error");
    }
  }

  function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runCardSearch(searchQuery);
  }

  function handleSearchQueryChange(value: string) {
    skipSuggestionFetchQueryRef.current = null;
    setSearchQuery(value);
    setSuggestionOpen(value.trim().length >= AUTOCOMPLETE_MIN_QUERY_LENGTH);
    setHighlightedSuggestionIndex(-1);
  }

  function handleSearchFieldFocus() {
    openSuggestionList();
  }

  function handleSuggestionRequestClose() {
    closeSuggestionList();
  }

  function handleSuggestionSelect(result: CatalogNameSearchRow) {
    const query = result.name.trim();
    options.onSearchActivity?.();
    skipSuggestionFetchQueryRef.current = query.toLowerCase();
    setSearchQuery(query);
    setSearchResults([result]);
    setSearchError(null);
    setSearchStatus("ready");
    closeSuggestionList();
  }

  function handleSearchInputKeyDown(
    event: ReactKeyboardEvent<HTMLInputElement>,
  ) {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        moveSuggestionHighlight(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        moveSuggestionHighlight(-1);
        break;
      case "Escape":
        if (suggestionOpen) {
          event.preventDefault();
          closeSuggestionList();
        }
        break;
      case "Enter": {
        const activeSuggestion =
          suggestionOpen && highlightedSuggestionIndex >= 0
            ? suggestionResults[highlightedSuggestionIndex]
            : null;
        if (activeSuggestion) {
          event.preventDefault();
          handleSuggestionSelect(activeSuggestion);
        }
        break;
      }
    }
  }

  async function loadSearchGroupPrintings(group: SearchCardGroup) {
    const cachedPrintings = printingLookupCacheRef.current[group.groupId];
    if (cachedPrintings) {
      return cachedPrintings;
    }

    const inFlightRequest = printingLookupPromisesRef.current[group.groupId];
    if (inFlightRequest) {
      return inFlightRequest;
    }

    const request = listCardPrintings(group.oracleId, { lang: "all" })
      .then((nextPrintings) => {
        if (!nextPrintings.length) {
          throw new Error(`No printings are currently available for ${group.name}.`);
        }
        printingLookupCacheRef.current[group.groupId] = nextPrintings;
        delete printingLookupPromisesRef.current[group.groupId];
        return nextPrintings;
      })
      .catch((error) => {
        delete printingLookupPromisesRef.current[group.groupId];
        throw error;
      });

    printingLookupPromisesRef.current[group.groupId] = request;
    return request;
  }

  const searchGroups = createSearchCardGroups(searchResults).slice(0, SEARCH_GROUP_LIMIT);

  return {
    handleSearchFieldFocus,
    handleSearchInputKeyDown,
    handleSearchQueryChange,
    handleSearchSubmit,
    handleSuggestionRequestClose,
    handleSuggestionSelect,
    highlightedSuggestionIndex,
    loadSearchGroupPrintings,
    resetSearchWorkspace,
    searchError,
    searchGroups,
    searchQuery,
    searchStatus,
    setHighlightedSuggestionIndex,
    suggestionError,
    suggestionOpen,
    suggestionResults,
    suggestionStatus,
  };
}
