import type { AddInventoryItemRequest, CatalogSearchRow, InventorySummary } from "../types";
import type { AsyncStatus, NoticeTone } from "../uiTypes";
import { PanelState } from "./ui/PanelState";
import { SearchResultCard } from "./SearchResultCard";

export function SearchPanel(props: {
  selectedInventoryRow: InventorySummary | null;
  searchStatus: AsyncStatus;
  searchError: string | null;
  searchQuery: string;
  searchResults: CatalogSearchRow[];
  busyAddCardId: string | null;
  onSearchQueryChange: (value: string) => void;
  onSearchSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  return (
    <section className="panel panel-featured">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Search And Add</p>
          <h2>Card Search</h2>
        </div>
        <span className="muted-note">
          Current inventory: {props.selectedInventoryRow?.display_name || "None"}
        </span>
      </div>

      <form className="search-form" onSubmit={props.onSearchSubmit}>
        <label className="field">
          <span>Search query</span>
          <input
            className="text-input"
            onChange={(event) => props.onSearchQueryChange(event.target.value)}
            placeholder="Lightning Bolt"
            value={props.searchQuery}
          />
        </label>
        <button className="primary-button" type="submit">
          {props.searchStatus === "loading" ? "Searching..." : "Search cards"}
        </button>
      </form>

      {!props.selectedInventoryRow ? (
        <p className="panel-hint">
          Search is available now. Choose an inventory to enable add actions.
        </p>
      ) : props.selectedInventoryRow.total_cards === 0 ? (
        <p className="panel-hint panel-hint-success">
          {props.selectedInventoryRow.display_name} starts empty on purpose. Use search results
          below to seed the first rows.
        </p>
      ) : null}

      <div className="search-results-grid">
        {props.searchStatus === "loading" && props.searchResults.length === 0 ? (
          <PanelState
            body="Looking up matching cards in the local catalog."
            title="Searching cards"
            variant="loading"
          />
        ) : props.searchStatus === "error" ? (
          <PanelState
            body={props.searchError || "Card search failed."}
            title="Search unavailable"
            variant="error"
          />
        ) : props.searchResults.length ? (
          props.searchResults.map((result) => (
            <SearchResultCard
              busy={props.busyAddCardId === result.scryfall_id}
              canAdd={Boolean(props.selectedInventoryRow)}
              key={result.scryfall_id}
              onAdd={props.onAdd}
              onNotice={props.onNotice}
              result={result}
            />
          ))
        ) : props.searchStatus === "ready" ? (
          <PanelState
            body="Try another card name, set code, or a broader search term."
            title="No matching cards"
          />
        ) : (
          <PanelState
            body="Search by card name to populate the add-card workflow."
            title="Run a search"
          />
        )}
      </div>
    </section>
  );
}
