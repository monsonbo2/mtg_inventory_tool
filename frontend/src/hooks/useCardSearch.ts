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
import type {
  CatalogNameSearchRow,
  CatalogPrintingLookupRow,
} from "../types";
import { toUserMessage } from "../uiHelpers";
import type { AsyncStatus } from "../uiTypes";

const AUTOCOMPLETE_MIN_QUERY_LENGTH = 2;
const AUTOCOMPLETE_DEBOUNCE_MS = 250;
const AUTOCOMPLETE_LIMIT = 8;
const SEARCH_GROUP_INITIAL_LIMIT = 8;
const SEARCH_GROUP_PAGE_SIZE = 10;
const SEARCH_GROUP_PREFETCH_LIMIT = SEARCH_GROUP_INITIAL_LIMIT + SEARCH_GROUP_PAGE_SIZE;

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
  const [searchTotalCount, setSearchTotalCount] = useState(0);
  const [searchGroupVisibleLimit, setSearchGroupVisibleLimit] = useState(SEARCH_GROUP_INITIAL_LIMIT);
  const [searchRequestedLimit, setSearchRequestedLimit] = useState(SEARCH_GROUP_PREFETCH_LIMIT);
  const [searchCanLoadMore, setSearchCanLoadMore] = useState(false);
  const [searchLoadMoreBusy, setSearchLoadMoreBusy] = useState(false);
  const [activeSearchGroupId, setActiveSearchGroupId] = useState<string | null>(null);
  const [searchResultsVisible, setSearchResultsVisible] = useState(false);
  const [searchWorkspaceMode, setSearchWorkspaceMode] = useState<"browse" | "focus">("browse");
  const [suggestionResults, setSuggestionResults] = useState<CatalogNameSearchRow[]>([]);
  const [suggestionOpen, setSuggestionOpen] = useState(false);
  const [highlightedSuggestionIndex, setHighlightedSuggestionIndex] = useState(-1);
  const suggestionLookupRequestIdRef = useRef(0);
  const suggestionCacheRef = useRef<Record<string, CatalogNameSearchRow[]>>({});
  const printingLookupCacheRef = useRef<Record<string, CatalogPrintingLookupRow[]>>({});
  const printingLookupPromisesRef = useRef<
    Record<string, Promise<CatalogPrintingLookupRow[]>>
  >({});
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
        .then((response) => {
          if (requestId !== suggestionLookupRequestIdRef.current) {
            return;
          }
          suggestionCacheRef.current[normalizedQuery] = response.items;
          setSuggestionResults(response.items);
          setSuggestionStatus("ready");
          setHighlightedSuggestionIndex(response.items.length ? 0 : -1);
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

  function resetSearchPagination() {
    setSearchGroupVisibleLimit(SEARCH_GROUP_INITIAL_LIMIT);
    setSearchRequestedLimit(SEARCH_GROUP_PREFETCH_LIMIT);
    setSearchCanLoadMore(false);
    setSearchLoadMoreBusy(false);
  }

  function resetSearchWorkspace() {
    suggestionLookupRequestIdRef.current += 1;
    skipSuggestionFetchQueryRef.current = null;
    setSearchQuery("");
    setSearchResults([]);
    setSearchTotalCount(0);
    setActiveSearchGroupId(null);
    setSearchResultsVisible(false);
    setSearchWorkspaceMode("browse");
    setSearchStatus("idle");
    setSearchError(null);
    resetSearchPagination();
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
        return direction > 0 ? 0 : -1;
      }

      const nextIndex = current + direction;
      if (nextIndex < 0) {
        return -1;
      }
      if (nextIndex >= suggestionResults.length) {
        return suggestionResults.length - 1;
      }
      return nextIndex;
    });
  }

  async function runCardSearch(
    query: string,
    runOptions: {
      loadingMore?: boolean;
      requestLimit?: number;
      visibleLimit?: number;
    } = {},
  ) {
    const trimmed = query.trim();
    const loadingMore = runOptions.loadingMore ?? false;
    const requestLimit = runOptions.requestLimit ?? SEARCH_GROUP_PREFETCH_LIMIT;
    const visibleLimit = runOptions.visibleLimit ?? SEARCH_GROUP_INITIAL_LIMIT;
    if (!trimmed) {
      setSearchResults([]);
      setSearchTotalCount(0);
      setActiveSearchGroupId(null);
      setSearchResultsVisible(false);
      setSearchWorkspaceMode("browse");
      setSearchStatus("idle");
      setSearchError(null);
      resetSearchPagination();
      return;
    }

    if (!loadingMore) {
      options.onSearchActivity?.();
      suggestionLookupRequestIdRef.current += 1;
      closeSuggestionList();
      setSearchStatus("loading");
      setSearchError(null);
      setSearchResultsVisible(false);
      setSearchWorkspaceMode("browse");
      setSearchLoadMoreBusy(false);
    } else {
      setSearchLoadMoreBusy(true);
    }

    try {
      const response = await searchCardNames({
        query: trimmed,
        limit: requestLimit,
      });
      const nextResults = response.items;
      const nextVisibleLimit = Math.min(visibleLimit, nextResults.length);
      const nextActiveSearchGroupId =
        activeSearchGroupId &&
        nextResults
          .slice(0, nextVisibleLimit)
          .some((result) => result.oracle_id === activeSearchGroupId)
          ? activeSearchGroupId
          : nextResults[0]?.oracle_id || null;
      setSearchResults(nextResults);
      setSearchTotalCount(response.total_count);
      setSearchGroupVisibleLimit(nextVisibleLimit);
      setSearchRequestedLimit(requestLimit);
      setSearchCanLoadMore(response.has_more);
      setActiveSearchGroupId(nextActiveSearchGroupId);
      setSearchResultsVisible(nextResults.length > 0);
      setSearchWorkspaceMode("browse");
      setSearchStatus("ready");
    } catch (error) {
      if (loadingMore) {
        setSearchError(toUserMessage(error, "More matching cards could not load."));
      } else {
        setSearchResults([]);
        setSearchTotalCount(0);
        setActiveSearchGroupId(null);
        setSearchResultsVisible(false);
        setSearchWorkspaceMode("browse");
        setSearchError(toUserMessage(error, "Card search failed."));
        setSearchStatus("error");
        resetSearchPagination();
      }
    } finally {
      if (loadingMore) {
        setSearchLoadMoreBusy(false);
      }
    }
  }

  function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runCardSearch(searchQuery);
  }

  function handleSearchQueryChange(value: string) {
    skipSuggestionFetchQueryRef.current = null;
    setSearchQuery(value);
    setSearchResults([]);
    setSearchTotalCount(0);
    setActiveSearchGroupId(null);
    setSearchResultsVisible(false);
    setSearchWorkspaceMode("browse");
    setSearchStatus("idle");
    setSearchError(null);
    resetSearchPagination();
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
    setSearchTotalCount(1);
    setSearchGroupVisibleLimit(1);
    setSearchRequestedLimit(1);
    setSearchCanLoadMore(false);
    setSearchLoadMoreBusy(false);
    setActiveSearchGroupId(result.oracle_id);
    setSearchResultsVisible(true);
    setSearchWorkspaceMode("focus");
    setSearchError(null);
    setSearchStatus("ready");
    closeSuggestionList();
  }

  function dismissSearchResults() {
    setSearchResultsVisible(false);
    setSearchLoadMoreBusy(false);
  }

  function handleSearchGroupSelect(groupId: string) {
    setActiveSearchGroupId(groupId);
    setSearchResultsVisible(true);
    setSearchWorkspaceMode("focus");
  }

  function handleSearchWorkspaceBrowse() {
    setSearchWorkspaceMode("browse");
    setSearchResultsVisible(true);
  }

  function handleSearchResultsLoadMore() {
    const hiddenLoadedResultCount = Math.max(0, searchResults.length - searchGroupVisibleLimit);
    const nextVisibleLimit = searchGroupVisibleLimit + SEARCH_GROUP_PAGE_SIZE;

    if (hiddenLoadedResultCount > 0) {
      setSearchGroupVisibleLimit(Math.min(nextVisibleLimit, searchResults.length));
      return;
    }

    if (!searchCanLoadMore || searchLoadMoreBusy) {
      return;
    }

    void runCardSearch(searchQuery, {
      loadingMore: true,
      requestLimit: searchRequestedLimit + SEARCH_GROUP_PAGE_SIZE,
      visibleLimit: nextVisibleLimit,
    });
  }

  function moveSearchGroupSelection(direction: 1 | -1) {
    const visibleSearchResults = searchResults.slice(0, searchGroupVisibleLimit);
    if (!searchResultsVisible || searchWorkspaceMode !== "browse" || visibleSearchResults.length <= 1) {
      return;
    }

    const currentIndex = Math.max(
      0,
      visibleSearchResults.findIndex((result) => result.oracle_id === activeSearchGroupId),
    );
    const nextIndex = Math.min(
      visibleSearchResults.length - 1,
      Math.max(0, currentIndex + direction),
    );
    setActiveSearchGroupId(
      visibleSearchResults[nextIndex]?.oracle_id || visibleSearchResults[0]?.oracle_id || null,
    );
  }

  function handleSearchInputKeyDown(
    event: ReactKeyboardEvent<HTMLInputElement>,
  ) {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (suggestionOpen) {
          moveSuggestionHighlight(1);
          break;
        }
        moveSearchGroupSelection(1);
        break;
      case "ArrowUp":
        event.preventDefault();
        if (suggestionOpen) {
          moveSuggestionHighlight(-1);
          break;
        }
        moveSearchGroupSelection(-1);
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
          break;
        }

        if (
          searchResultsVisible &&
          searchWorkspaceMode === "browse" &&
          searchResults.slice(0, searchGroupVisibleLimit).length > 1 &&
          activeSearchGroupId
        ) {
          event.preventDefault();
          handleSearchGroupSelect(activeSearchGroupId);
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

  const searchLoadedHiddenResultCount = Math.max(
    0,
    searchResults.length - searchGroupVisibleLimit,
  );
  const searchHiddenResultCount = Math.max(0, searchTotalCount - searchGroupVisibleLimit);
  const visibleSearchResults = searchResults.slice(0, searchGroupVisibleLimit);
  const searchGroups = createSearchCardGroups(visibleSearchResults);

  return {
    handleSearchFieldFocus,
    handleSearchInputKeyDown,
    handleSearchQueryChange,
    handleSearchResultsLoadMore,
    handleSearchSubmit,
    dismissSearchResults,
    handleSearchGroupSelect,
    handleSearchWorkspaceBrowse,
    handleSuggestionRequestClose,
    handleSuggestionSelect,
    activeSearchGroupId,
    highlightedSuggestionIndex,
    loadSearchGroupPrintings,
    resetSearchWorkspace,
    searchError,
    searchCanLoadMore: searchLoadedHiddenResultCount > 0 || searchCanLoadMore,
    searchGroups,
    searchHiddenResultCount,
    searchLoadedHiddenResultCount,
    searchLoadMoreBusy,
    searchQuery,
    searchResultsVisible,
    searchTotalCount,
    searchWorkspaceMode,
    searchStatus,
    setHighlightedSuggestionIndex,
    suggestionError,
    suggestionOpen,
    suggestionResults,
    suggestionStatus,
  };
}
