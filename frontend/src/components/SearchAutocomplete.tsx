import { CardThumbnail } from "./ui/CardThumbnail";
import type { CatalogSearchRow } from "../types";
import type { AsyncStatus } from "../uiTypes";

export function SearchAutocomplete(props: {
  highlightedIndex: number;
  isOpen: boolean;
  listboxId: string;
  onHighlight: (index: number) => void;
  onSelect: (result: CatalogSearchRow) => void;
  optionIdPrefix: string;
  query: string;
  results: CatalogSearchRow[];
  status: AsyncStatus;
  error: string | null;
}) {
  if (!props.isOpen || props.query.trim().length < 2) {
    return null;
  }

  return (
    <div
      aria-label="Card suggestions"
      className="search-autocomplete"
      id={props.listboxId}
      role="listbox"
    >
      {props.status === "loading" ? (
        <div className="search-autocomplete-state">
          <strong>Loading suggestions...</strong>
          <span>Searching the local card catalog as you type.</span>
        </div>
      ) : props.status === "error" ? (
        <div className="search-autocomplete-state">
          <strong>Suggestions unavailable</strong>
          <span>{props.error || "Suggestions could not load right now."}</span>
        </div>
      ) : props.results.length ? (
        <div className="search-autocomplete-list">
          {props.results.map((result, index) => (
            <button
              aria-selected={index === props.highlightedIndex}
              className={
                index === props.highlightedIndex
                  ? "search-autocomplete-item search-autocomplete-item-active"
                  : "search-autocomplete-item"
              }
              id={`${props.optionIdPrefix}-option-${index}`}
              key={result.scryfall_id}
              onMouseDown={(event) => {
                event.preventDefault();
                props.onSelect(result);
              }}
              onMouseEnter={() => props.onHighlight(index)}
              role="option"
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
                  {result.set_name} · #{result.collector_number}
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
