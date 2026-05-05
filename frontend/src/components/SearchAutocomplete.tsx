import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CardThumbnail } from "./ui/CardThumbnail";
import type { CatalogNameSearchRow } from "../types";
import type { AsyncStatus } from "../uiTypes";
import { formatLanguageCode } from "../uiHelpers";

function getSuggestionPeekHeight(optionNode: HTMLElement | null) {
  if (!optionNode) {
    return 40;
  }

  return Math.min(48, Math.max(40, Math.round(optionNode.offsetHeight * 0.55)));
}

function scrollSuggestionListForActiveOption(options: {
  activeNode: HTMLButtonElement;
  adjacentNode: HTMLButtonElement | null;
  direction: "down" | "up" | null;
  listNode: HTMLDivElement;
}) {
  const { activeNode, adjacentNode, direction, listNode } = options;
  const listRect = listNode.getBoundingClientRect();
  const visibleListHeight =
    typeof window === "undefined"
      ? listNode.clientHeight
      : Math.max(
          0,
          Math.min(listNode.clientHeight, window.innerHeight - listRect.top - 20),
        );
  const effectiveListHeight = visibleListHeight || listNode.clientHeight;
  const maxScrollTop = Math.max(0, listNode.scrollHeight - effectiveListHeight);
  if (maxScrollTop <= 0) {
    return;
  }

  const currentScrollTop = listNode.scrollTop;
  const activeTop = activeNode.offsetTop;
  const activeBottom = activeTop + activeNode.offsetHeight;
  const peekHeight = getSuggestionPeekHeight(adjacentNode);

  let nextScrollTop = currentScrollTop;
  const targetTop = direction === "up" ? Math.max(0, activeTop - peekHeight) : activeTop;
  const targetBottom =
    direction === "down"
      ? Math.min(listNode.scrollHeight, activeBottom + peekHeight)
      : activeBottom;

  if (targetBottom > currentScrollTop + effectiveListHeight) {
    nextScrollTop = targetBottom - effectiveListHeight;
  }

  if (targetTop < nextScrollTop) {
    nextScrollTop = targetTop;
  }

  nextScrollTop = Math.max(0, Math.min(maxScrollTop, Math.ceil(nextScrollTop)));
  if (Math.abs(nextScrollTop - currentScrollTop) < 1) {
    return;
  }

  if (typeof listNode.scrollTo === "function") {
    listNode.scrollTo({ top: nextScrollTop });
    return;
  }

  listNode.scrollTop = nextScrollTop;
}

export function SearchAutocomplete(props: {
  highlightedIndex: number;
  isOpen: boolean;
  listboxId: string;
  onHighlight: (index: number) => void;
  onSelect: (result: CatalogNameSearchRow) => void;
  optionIdPrefix: string;
  query: string;
  results: CatalogNameSearchRow[];
  status: AsyncStatus;
  error: string | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const optionRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const previousHighlightedIndexRef = useRef<number | null>(null);
  const [listMaxHeight, setListMaxHeight] = useState<number | null>(null);

  useLayoutEffect(() => {
    if (!props.isOpen || !props.results.length || typeof window === "undefined") {
      setListMaxHeight(null);
      return;
    }

    function updateListMaxHeight() {
      const containerNode = containerRef.current;
      if (!containerNode) {
        return;
      }

      const containerRect = containerNode.getBoundingClientRect();
      const availableViewportHeight = Math.floor(window.innerHeight - containerRect.top - 20);
      const nextMaxHeight = Math.max(120, Math.min(560, availableViewportHeight));
      setListMaxHeight((currentMaxHeight) =>
        currentMaxHeight === nextMaxHeight ? currentMaxHeight : nextMaxHeight,
      );
    }

    updateListMaxHeight();
    window.addEventListener("resize", updateListMaxHeight);
    window.addEventListener("scroll", updateListMaxHeight, true);
    return () => {
      window.removeEventListener("resize", updateListMaxHeight);
      window.removeEventListener("scroll", updateListMaxHeight, true);
    };
  }, [props.isOpen, props.results.length]);

  useEffect(() => {
    if (!props.isOpen || !props.results.length || props.highlightedIndex < 0) {
      previousHighlightedIndexRef.current = null;
      return;
    }

    const listNode = listRef.current;
    const activeResult = props.results[props.highlightedIndex];
    const activeNode = activeResult
      ? optionRefs.current[activeResult.oracle_id]
      : null;
    if (!listNode || !activeNode) {
      previousHighlightedIndexRef.current = props.highlightedIndex;
      return;
    }

    const previousHighlightedIndex = previousHighlightedIndexRef.current;
    const direction =
      previousHighlightedIndex === null || previousHighlightedIndex === props.highlightedIndex
        ? null
        : props.highlightedIndex > previousHighlightedIndex
          ? "down"
          : "up";
    const adjacentIndex =
      direction === "up"
        ? props.highlightedIndex - 1
        : direction === "down" && props.highlightedIndex + 1 < props.results.length
          ? props.highlightedIndex + 1
          : -1;
    const adjacentNode =
      adjacentIndex >= 0
        ? optionRefs.current[props.results[adjacentIndex]?.oracle_id ?? ""]
        : null;

    scrollSuggestionListForActiveOption({
      activeNode,
      adjacentNode,
      direction,
      listNode,
    });

    previousHighlightedIndexRef.current = props.highlightedIndex;
  }, [props.highlightedIndex, props.isOpen, props.results]);

  if (!props.isOpen || props.query.trim().length < 2) {
    return null;
  }

  return (
    <div
      aria-label="Card suggestions"
      aria-busy={props.status === "loading"}
      className="search-autocomplete"
      id={props.listboxId}
      ref={containerRef}
      role="listbox"
    >
      {props.status === "loading" ? (
        <div className="search-autocomplete-state">
          <strong>Loading suggestions...</strong>
          <span>Looking for matching cards as you type.</span>
        </div>
      ) : props.status === "error" ? (
        <div className="search-autocomplete-state">
          <strong>Suggestions unavailable</strong>
          <span>{props.error || "Suggestions could not load right now."}</span>
        </div>
      ) : props.results.length ? (
        <div
          className="search-autocomplete-list"
          ref={listRef}
          style={listMaxHeight ? { maxHeight: `${listMaxHeight}px` } : undefined}
        >
          {props.results.map((result, index) => (
            <button
              aria-selected={index === props.highlightedIndex}
              className={
                index === props.highlightedIndex
                  ? "search-autocomplete-item search-autocomplete-item-active"
                  : "search-autocomplete-item"
              }
              id={`${props.optionIdPrefix}-option-${index}`}
              key={result.oracle_id}
              onMouseDown={(event) => {
                event.preventDefault();
                props.onSelect(result);
              }}
              onMouseEnter={() => props.onHighlight(index)}
              onFocus={() => props.onHighlight(index)}
              role="option"
              ref={(node) => {
                optionRefs.current[result.oracle_id] = node;
              }}
              tabIndex={-1}
              type="button"
            >
              <CardThumbnail
                imageUrl={result.image_uri_small}
                imageUrlLarge={result.image_uri_normal}
                name={result.name}
                variant="search"
              />
              <span className="search-autocomplete-copy">
                <strong>{result.name}</strong>
                <span className="search-autocomplete-meta">
                  {result.printings_count} printing{result.printings_count === 1 ? "" : "s"} ·{" "}
                  {result.available_languages.map((languageCode) => formatLanguageCode(languageCode)).join(", ")}
                </span>
              </span>
            </button>
          ))}
        </div>
      ) : props.status === "ready" ? (
        <div className="search-autocomplete-state">
          <strong>No suggestions yet</strong>
          <span>Keep typing or press search to run the full result view.</span>
        </div>
      ) : null}
    </div>
  );
}
