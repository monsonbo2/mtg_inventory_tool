import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import {
  addInventoryItem,
  ApiClientError,
  deleteInventoryItem,
  listInventories,
  listInventoryAudit,
  listInventoryItems,
  patchInventoryItem,
  searchCards,
} from "./api";
import type {
  AddInventoryItemRequest,
  CatalogSearchRow,
  FinishInput,
  FinishValue,
  InventoryAuditEvent,
  InventoryItemPatchResponse,
  InventorySummary,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
} from "./types";

const FINISH_OPTIONS: Array<{ value: FinishValue; label: string }> = [
  { value: "normal", label: "Normal" },
  { value: "foil", label: "Foil" },
  { value: "etched", label: "Etched" },
];

type AsyncStatus = "idle" | "loading" | "ready" | "error";
type ViewRefreshOutcome = "applied" | "skipped";
type NoticeTone = "info" | "success" | "error";
type ItemMutationAction =
  | "quantity"
  | "finish"
  | "location"
  | "notes"
  | "tags"
  | "delete";

type ItemMutationState = {
  itemId: number;
  action: ItemMutationAction;
};

type NoticeState = {
  message: string;
  tone: NoticeTone;
};

export default function App() {
  const [inventories, setInventories] = useState<InventorySummary[]>([]);
  const [selectedInventory, setSelectedInventory] = useState<string | null>(null);
  const [items, setItems] = useState<OwnedInventoryRow[]>([]);
  const [auditEvents, setAuditEvents] = useState<InventoryAuditEvent[]>([]);
  const [inventoryStatus, setInventoryStatus] = useState<AsyncStatus>("loading");
  const [viewStatus, setViewStatus] = useState<AsyncStatus>("idle");
  const [searchStatus, setSearchStatus] = useState<AsyncStatus>("idle");
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("Lightning Bolt");
  const [searchResults, setSearchResults] = useState<CatalogSearchRow[]>([]);
  const [busyItem, setBusyItem] = useState<ItemMutationState | null>(null);
  const [busyAddCardId, setBusyAddCardId] = useState<string | null>(null);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const selectedInventoryRef = useRef<string | null>(null);
  const inventoryViewRequestIdRef = useRef(0);

  useEffect(() => {
    selectedInventoryRef.current = selectedInventory;
  }, [selectedInventory]);

  useEffect(() => {
    let cancelled = false;

    async function loadInventoriesOnStart() {
      setInventoryStatus("loading");
      setInventoryError(null);

      try {
        const nextInventories = await listInventories();
        if (cancelled) {
          return;
        }
        setInventories(nextInventories);
        setInventoryError(null);
        setSelectedInventory((current) => {
          return resolveSelectedInventorySlug(nextInventories, current);
        });
        setInventoryStatus("ready");
      } catch (error) {
        if (cancelled) {
          return;
        }
        setInventoryError(toUserMessage(error, "Could not load inventories."));
        setInventoryStatus("error");
      }
    }

    void loadInventoriesOnStart();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedInventory) {
      inventoryViewRequestIdRef.current += 1;
      setItems([]);
      setAuditEvents([]);
      setViewError(null);
      setViewStatus("idle");
      return;
    }

    void loadInventoryOverview(selectedInventory);
  }, [selectedInventory]);

  async function reloadInventorySummaries(preferredSlug: string) {
    try {
      const nextInventories = await listInventories();
      setInventories(nextInventories);
      setInventoryError(null);
      setInventoryStatus("ready");

      const nextSelectedInventory = resolveSelectedInventorySlug(
        nextInventories,
        selectedInventoryRef.current ?? preferredSlug,
      );

      if (nextSelectedInventory !== selectedInventoryRef.current) {
        selectedInventoryRef.current = nextSelectedInventory;
        setSelectedInventory(nextSelectedInventory);
      }
    } catch (error) {
      setInventoryError(toUserMessage(error, "Could not refresh inventory totals."));
      setInventoryStatus("error");
    }
  }

  async function loadInventoryOverview(
    inventorySlug: string,
    options: { reloadInventories?: boolean; showLoading?: boolean } = {},
  ): Promise<ViewRefreshOutcome> {
    const requestId = ++inventoryViewRequestIdRef.current;

    if (options.showLoading !== false && selectedInventoryRef.current === inventorySlug) {
      setViewStatus("loading");
      setViewError(null);
    }

    try {
      const [nextItems, nextAuditEvents] = await Promise.all([
        listInventoryItems(inventorySlug),
        listInventoryAudit(inventorySlug),
      ]);

      if (
        requestId !== inventoryViewRequestIdRef.current ||
        selectedInventoryRef.current !== inventorySlug
      ) {
        return "skipped";
      }

      setItems(nextItems);
      setAuditEvents(nextAuditEvents);
      setViewError(null);
      setViewStatus("ready");

      if (options.reloadInventories) {
        void reloadInventorySummaries(inventorySlug);
      }

      return "applied";
    } catch (error) {
      if (
        requestId !== inventoryViewRequestIdRef.current ||
        selectedInventoryRef.current !== inventorySlug
      ) {
        return "skipped";
      }

      setViewError(
        toUserMessage(
          error,
          `Could not load collection data for '${inventorySlug}'.`,
        ),
      );
      setViewStatus("error");
      throw error;
    }
  }

  async function refreshAfterMutation(inventorySlug: string, successMessage: string) {
    try {
      await loadInventoryOverview(inventorySlug, { reloadInventories: true });
      showNotice(successMessage, "success");
    } catch {
      showNotice(
        `${successMessage} The latest view could not refresh automatically.`,
        "error",
      );
    }
  }

  function showNotice(message: string, tone: NoticeTone = "info") {
    setNotice({ message, tone });
  }

  function reportNotice(message: string, tone: NoticeTone = "info") {
    showNotice(message, tone);
  }

  function requireSelectedInventory(message: string) {
    const inventorySlug = selectedInventoryRef.current;
    if (!inventorySlug) {
      showNotice(message);
      return null;
    }
    return inventorySlug;
  }

  function describeInventory(inventorySlug: string) {
    return (
      inventories.find((inventory) => inventory.slug === inventorySlug)?.display_name ||
      inventorySlug
    );
  }

  async function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmed = searchQuery.trim();
    if (!trimmed) {
      setSearchResults([]);
      setSearchStatus("idle");
      setSearchError(null);
      return;
    }

    setSearchStatus("loading");
    setSearchError(null);
    setNotice(null);

    try {
      const results = await searchCards({ query: trimmed, limit: 8 });
      setSearchResults(results);
      setSearchStatus("ready");
    } catch (error) {
      setSearchResults([]);
      setSearchError(toUserMessage(error, "Card search failed."));
      setSearchStatus("error");
    }
  }

  async function handleAddCard(payload: AddInventoryItemRequest) {
    const inventorySlug = requireSelectedInventory(
      "Select an inventory before adding a card.",
    );
    if (!inventorySlug) {
      return false;
    }

    setBusyAddCardId(payload.scryfall_id);
    setNotice(null);

    try {
      const response = await addInventoryItem(inventorySlug, payload);
      await refreshAfterMutation(
        inventorySlug,
        `Added ${response.card_name} to ${describeInventory(inventorySlug)}.`,
      );
      return true;
    } catch (error) {
      showNotice(toUserMessage(error, "Could not add the card."), "error");
      return false;
    } finally {
      setBusyAddCardId(null);
    }
  }

  async function handlePatchItem(
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) {
    const inventorySlug = requireSelectedInventory(
      "Select an inventory before editing collection rows.",
    );
    if (!inventorySlug) {
      return;
    }

    setBusyItem({ itemId, action });
    setNotice(null);

    try {
      const response = await patchInventoryItem(inventorySlug, itemId, payload);
      await refreshAfterMutation(
        inventorySlug,
        getPatchSuccessMessage(response, describeInventory(inventorySlug)),
      );
    } catch (error) {
      showNotice(toUserMessage(error, "Could not save the change."), "error");
    } finally {
      setBusyItem(null);
    }
  }

  async function handleDeleteItem(itemId: number, cardName: string) {
    const inventorySlug = requireSelectedInventory(
      "Select an inventory before removing collection rows.",
    );
    if (!inventorySlug) {
      return;
    }

    setBusyItem({ itemId, action: "delete" });
    setNotice(null);

    try {
      const response = await deleteInventoryItem(inventorySlug, itemId);
      await refreshAfterMutation(
        inventorySlug,
        `Removed ${response.card_name || cardName} from ${describeInventory(inventorySlug)}.`,
      );
    } catch (error) {
      showNotice(toUserMessage(error, "Could not remove the card."), "error");
    } finally {
      setBusyItem(null);
    }
  }

  const selectedInventoryRow =
    inventories.find((inventory) => inventory.slug === selectedInventory) ?? null;
  const totalEstimatedValue = items.reduce(
    (sum, row) => sum + decimalToNumber(row.est_value),
    0,
  );

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Local Demo Frontend</p>
          <h1>MTG Inventory Studio</h1>
          <p className="hero-copy">
            A local inventory workbench for the demo app. The frontend now
            tracks the current HTTP contract, supports seeded multi-inventory
            states, and is ready for a final Stage 1 signoff pass.
          </p>
        </div>
        <div className="hero-metrics">
          <MetricCard
            accent="Sunrise"
            label="Inventories"
            value={String(inventories.length)}
          />
          <MetricCard
            accent="Lagoon"
            label="Rows In View"
            value={String(items.length)}
          />
          <MetricCard
            accent="Paper"
            label="Est. Value"
            value={formatUsd(totalEstimatedValue)}
          />
        </div>
      </header>

      {notice ? (
        <div
          aria-live={notice.tone === "error" ? "assertive" : "polite"}
          className={`notice-banner notice-banner-${notice.tone}`}
          role={notice.tone === "error" ? "alert" : "status"}
        >
          {notice.message}
        </div>
      ) : null}

      <div className="workspace-grid">
        <aside className="sidebar-column">
          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Collection Scope</p>
                <h2>Inventories</h2>
              </div>
              <span className={`status-pill status-${inventoryStatus}`}>
                {formatStatusLabel(inventoryStatus)}
              </span>
            </div>

            {inventoryError && inventories.length ? (
              <p className="panel-error">{inventoryError}</p>
            ) : null}

            <div className="inventory-nav">
              {inventoryStatus === "loading" && inventories.length === 0 ? (
                <PanelState
                  body="Looking for available local demo inventories."
                  compact
                  title="Loading inventories"
                  variant="loading"
                />
              ) : inventoryStatus === "error" && inventories.length === 0 ? (
                <PanelState
                  body={inventoryError || "Could not load inventories right now."}
                  compact
                  title="Inventories unavailable"
                  variant="error"
                />
              ) : inventories.length ? (
                inventories.map((inventory) => (
                  <button
                    key={inventory.slug}
                    className={
                      inventory.slug === selectedInventory
                        ? "inventory-button inventory-button-active"
                        : "inventory-button"
                    }
                    onClick={() => setSelectedInventory(inventory.slug)}
                    type="button"
                  >
                    <div className="inventory-button-head">
                      <span className="inventory-button-title">
                        {inventory.display_name}
                      </span>
                      <span
                        className={
                          inventory.total_cards === 0
                            ? "inventory-state-chip inventory-state-chip-empty"
                            : "inventory-state-chip"
                        }
                      >
                        {inventory.total_cards === 0 ? "Empty" : "Active"}
                      </span>
                    </div>
                    <span className="inventory-button-meta">
                      {inventory.item_rows} rows · {inventory.total_cards} cards
                    </span>
                    {inventory.description ? (
                      <span className="inventory-button-description">
                        {inventory.description}
                      </span>
                    ) : null}
                  </button>
                ))
              ) : (
                <PanelState
                  body="Create or seed an inventory to start the local demo."
                  compact
                  title="No inventories yet"
                />
              )}
            </div>

            {selectedInventoryRow ? (
              <div className="inventory-focus-card">
                <div className="inventory-focus-header">
                  <strong>{selectedInventoryRow.display_name}</strong>
                  <span
                    className={
                      selectedInventoryRow.total_cards === 0
                        ? "inventory-state-chip inventory-state-chip-empty"
                        : "inventory-state-chip"
                    }
                  >
                    {selectedInventoryRow.total_cards === 0 ? "Ready for first add" : "Loaded"}
                  </span>
                </div>
                <p>
                  {selectedInventoryRow.description || "No description provided for this inventory."}
                </p>
              </div>
            ) : null}
          </section>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Recent Activity</p>
                <h2>Audit Feed</h2>
              </div>
              <span className="muted-note">Latest 12 events</span>
            </div>

            {viewError && auditEvents.length ? (
              <p className="panel-error">{viewError}</p>
            ) : null}

            <div className="audit-list">
              {!selectedInventoryRow ? (
                <PanelState
                  body="Choose an inventory to inspect its recent write activity."
                  compact
                  title="Pick an inventory"
                />
              ) : viewStatus === "loading" && auditEvents.length === 0 ? (
                <PanelState
                  body="Fetching the most recent audit entries for this inventory."
                  compact
                  title="Loading activity"
                  variant="loading"
                />
              ) : viewStatus === "error" && auditEvents.length === 0 ? (
                <PanelState
                  body={viewError || "Could not load recent activity for this inventory."}
                  compact
                  title="Activity unavailable"
                  variant="error"
                />
              ) : auditEvents.length ? (
                auditEvents.map((event) => (
                  <article
                    className="audit-card"
                    key={event.id}
                  >
                    <div className="audit-card-topline">
                      <span className="audit-action">{formatAuditAction(event.action)}</span>
                      <span className="audit-time">
                        {formatTimestamp(event.occurred_at)}
                      </span>
                    </div>
                    <p className="audit-meta">
                      Actor: {formatAuditActor(event)}
                    </p>
                    <p className="audit-meta">
                      Item: {event.item_id ? `#${event.item_id}` : "inventory"}
                    </p>
                    {event.request_id ? (
                      <p className="audit-meta">Request: {event.request_id}</p>
                    ) : null}
                  </article>
                ))
              ) : (
                <PanelState
                  body={getInventoryAuditEmptyMessage(selectedInventoryRow)}
                  compact
                  title={selectedInventoryRow.total_cards === 0 ? "No activity yet in this inventory" : "No recent activity"}
                />
              )}
            </div>
          </section>
        </aside>

        <main className="content-column">
          <section className="panel panel-featured">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Search And Add</p>
                <h2>Card Search</h2>
              </div>
              <span className="muted-note">
                Current inventory: {selectedInventoryRow?.display_name || "None"}
              </span>
            </div>

            <form
              className="search-form"
              onSubmit={handleSearchSubmit}
            >
              <label className="field">
                <span>Search query</span>
                <input
                  className="text-input"
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Lightning Bolt"
                  value={searchQuery}
                />
              </label>
              <button
                className="primary-button"
                type="submit"
              >
                {searchStatus === "loading" ? "Searching..." : "Search cards"}
              </button>
            </form>

            {!selectedInventoryRow ? (
              <p className="panel-hint">
                Search is available now. Choose an inventory to enable add actions.
              </p>
            ) : selectedInventoryRow.total_cards === 0 ? (
              <p className="panel-hint panel-hint-success">
                {selectedInventoryRow.display_name} starts empty on purpose. Use search results
                below to seed the first rows.
              </p>
            ) : null}

            <div className="search-results-grid">
              {searchStatus === "loading" && searchResults.length === 0 ? (
                <PanelState
                  body="Looking up matching cards in the local catalog."
                  title="Searching cards"
                  variant="loading"
                />
              ) : searchStatus === "error" ? (
                <PanelState
                  body={searchError || "Card search failed."}
                  title="Search unavailable"
                  variant="error"
                />
              ) : searchResults.length ? (
                searchResults.map((result) => (
                  <SearchResultCard
                    busy={busyAddCardId === result.scryfall_id}
                    canAdd={Boolean(selectedInventoryRow)}
                    key={result.scryfall_id}
                    onAdd={handleAddCard}
                    onNotice={reportNotice}
                    result={result}
                  />
                ))
              ) : searchStatus === "ready" ? (
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

          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Collection View</p>
                <h2>Owned Rows</h2>
              </div>
              <span className={`status-pill status-${viewStatus}`}>
                {formatStatusLabel(viewStatus)}
              </span>
            </div>

            <div className="inventory-summary-bar">
              <div className="summary-chip">
                <span>Inventory</span>
                <strong>{selectedInventoryRow?.display_name || "No inventory"}</strong>
              </div>
              <div className="summary-chip">
                <span>Total cards</span>
                <strong>{selectedInventoryRow?.total_cards ?? 0}</strong>
              </div>
              <div className="summary-chip">
                <span>Estimated value</span>
                <strong>{formatUsd(totalEstimatedValue)}</strong>
              </div>
            </div>

            {viewError && items.length ? <p className="panel-error">{viewError}</p> : null}

            <div className="collection-grid">
              {!selectedInventoryRow ? (
                <PanelState
                  body="Choose an inventory on the left to load owned rows and pricing."
                  title="No inventory selected"
                />
              ) : viewStatus === "loading" && items.length === 0 ? (
                <PanelState
                  body="Fetching owned rows, prices, and tags for this inventory."
                  title="Loading collection"
                  variant="loading"
                />
              ) : viewStatus === "error" && items.length === 0 ? (
                <PanelState
                  body={viewError || "Could not load collection rows for this inventory."}
                  title="Collection unavailable"
                  variant="error"
                />
              ) : items.length ? (
                items.map((item) => (
                  <OwnedItemCard
                    busyAction={busyItem?.itemId === item.item_id ? busyItem.action : null}
                    item={item}
                    key={item.item_id}
                    onDelete={handleDeleteItem}
                    onNotice={reportNotice}
                    onPatch={handlePatchItem}
                  />
                ))
              ) : (
                <PanelState
                  body={getInventoryCollectionEmptyMessage(selectedInventoryRow)}
                  title={`${selectedInventoryRow.display_name} is empty`}
                />
              )}
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}

function MetricCard(props: { label: string; value: string; accent: string }) {
  return (
    <article className="metric-card">
      <span className="metric-accent">{props.accent}</span>
      <strong>{props.value}</strong>
      <span>{props.label}</span>
    </article>
  );
}

function SearchResultCard(props: {
  result: CatalogSearchRow;
  busy: boolean;
  canAdd: boolean;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  const [quantity, setQuantity] = useState("1");
  const [finish, setFinish] = useState<FinishValue>(props.result.finishes[0] || "normal");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [recentlyAdded, setRecentlyAdded] = useState(false);

  useEffect(() => {
    if (!recentlyAdded) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setRecentlyAdded(false);
    }, 1800);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [recentlyAdded]);

  const parsedQuantity = Number.parseInt(quantity, 10);
  const parsedTags = parseTags(tags);
  const trimmedLocation = location.trim();
  const trimmedNotes = notes.trim();
  const quantityIsValid = Number.isInteger(parsedQuantity) && parsedQuantity > 0;
  const optionalDetailSummary =
    [
      trimmedLocation ? `Location: ${trimmedLocation}` : null,
      parsedTags.length ? `${parsedTags.length} tag${parsedTags.length === 1 ? "" : "s"}` : null,
      trimmedNotes ? "Note ready" : null,
    ].filter(Boolean).join(" · ") || "No optional details yet";
  const addButtonLabel = props.busy
    ? "Adding..."
    : recentlyAdded
      ? "Added"
      : !props.canAdd
        ? "Select inventory"
        : quantityIsValid
          ? "Add to inventory"
          : "Enter valid qty";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!props.canAdd) {
      props.onNotice("Select an inventory before adding a card.");
      return;
    }

    if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) {
      props.onNotice("Enter a whole-number quantity greater than 0.", "error");
      return;
    }

    const didAdd = await props.onAdd({
      scryfall_id: props.result.scryfall_id,
      quantity: parsedQuantity,
      finish,
      location: trimmedLocation || undefined,
      notes: trimmedNotes || null,
      tags: parsedTags,
    });
    if (didAdd) {
      setRecentlyAdded(true);
    }
  }

  const availableFinishes = FINISH_OPTIONS.filter((option) =>
    props.result.finishes.includes(option.value),
  );

  return (
    <article className="result-card">
      <div className="card-hero">
        <CardThumbnail
          imageUrl={props.result.image_uri_small}
          imageUrlLarge={props.result.image_uri_normal}
          name={props.result.name}
          variant="search"
        />

        <div className="card-hero-body">
          <div className="result-card-header">
            <div>
              <h3>{props.result.name}</h3>
              <p className="result-card-subtitle">
                {props.result.set_name} · #{props.result.collector_number}
              </p>
            </div>
            <span className="rarity-pill">{props.result.rarity || "unknown"}</span>
          </div>

          <div className="tag-row">
            <span className="tag-chip">{props.result.set_code.toUpperCase()}</span>
            <span className="tag-chip">{props.result.lang.toUpperCase()}</span>
            {props.result.finishes.map((value) => (
              <span
                className="tag-chip subdued"
                key={value}
              >
                {formatFinishLabel(value)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <form
        className="add-card-form"
        onSubmit={handleSubmit}
      >
        <div className="form-section">
          <div className="form-section-header">
            <strong>Quick add</strong>
            <span>
              {quantityIsValid
                ? `${parsedQuantity}x ${formatFinishLabel(finish)}`
                : "Choose quantity and finish"}
            </span>
          </div>

          <div className="mini-grid">
            <label className="field">
              <span>Qty</span>
              <input
                className="text-input"
                disabled={props.busy || !props.canAdd}
                min="1"
                onChange={(event) => {
                  setQuantity(event.target.value);
                  setRecentlyAdded(false);
                }}
                type="number"
                value={quantity}
              />
            </label>

            <label className="field">
              <span>Finish</span>
              <select
                className="text-input"
                disabled={props.busy || !props.canAdd}
                onChange={(event) => {
                  setFinish(event.target.value as FinishValue);
                  setRecentlyAdded(false);
                }}
                value={finish}
              >
                {availableFinishes.map((option) => (
                  <option
                    key={option.value}
                    value={option.value}
                  >
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="form-section form-section-muted">
          <div className="form-section-header">
            <strong>Optional row details</strong>
            <span>{optionalDetailSummary}</span>
          </div>

          <label className="field">
            <span>Location</span>
            <input
              className="text-input"
              disabled={props.busy || !props.canAdd}
              onChange={(event) => {
                setLocation(event.target.value);
                setRecentlyAdded(false);
              }}
              placeholder="Red Binder"
              value={location}
            />
          </label>

          <label className="field">
            <span>Tags</span>
            <input
              className="text-input"
              disabled={props.busy || !props.canAdd}
              onChange={(event) => {
                setTags(event.target.value);
                setRecentlyAdded(false);
              }}
              placeholder="burn, trade"
              value={tags}
            />
          </label>

          <label className="field">
            <span>Notes</span>
            <textarea
              className="text-area"
              disabled={props.busy || !props.canAdd}
              onChange={(event) => {
                setNotes(event.target.value);
                setRecentlyAdded(false);
              }}
              placeholder="Optional add-note for the row"
              rows={3}
              value={notes}
            />
          </label>
        </div>

        {!quantityIsValid ? (
          <p className="field-hint field-hint-error">
            Enter a whole-number quantity greater than 0.
          </p>
        ) : recentlyAdded ? (
          <p className="field-hint field-hint-success">
            Added successfully. You can adjust the form and add another copy.
          </p>
        ) : null}

        <button
          className="primary-button"
          disabled={props.busy || !props.canAdd || !quantityIsValid}
          type="submit"
        >
          {addButtonLabel}
        </button>
      </form>
    </article>
  );
}

function OwnedItemCard(props: {
  item: OwnedInventoryRow;
  busyAction: ItemMutationAction | null;
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<void>;
  onDelete: (itemId: number, cardName: string) => Promise<void>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  const [quantity, setQuantity] = useState(String(props.item.quantity));
  const [finish, setFinish] = useState<FinishValue>(props.item.finish);
  const [location, setLocation] = useState(props.item.location || "");
  const [notes, setNotes] = useState(props.item.notes || "");
  const [tags, setTags] = useState(props.item.tags.join(", "));

  useEffect(() => {
    setQuantity(String(props.item.quantity));
    setFinish(props.item.finish);
    setLocation(props.item.location || "");
    setNotes(props.item.notes || "");
    setTags(props.item.tags.join(", "));
  }, [
    props.item.finish,
    props.item.item_id,
    props.item.location,
    props.item.notes,
    props.item.quantity,
    props.item.tags,
  ]);

  async function saveQuantity() {
    if (!quantityIsValid) {
      props.onNotice("Enter a whole-number quantity greater than 0.", "error");
      return;
    }
    await props.onPatch(props.item.item_id, "quantity", { quantity: parsedQuantity });
  }

  async function saveFinish() {
    await props.onPatch(props.item.item_id, "finish", { finish });
  }

  async function saveLocation() {
    const trimmed = location.trim();
    await props.onPatch(
      props.item.item_id,
      "location",
      trimmed ? { location: trimmed } : { clear_location: true },
    );
  }

  async function saveNotes() {
    const trimmed = notes.trim();
    await props.onPatch(
      props.item.item_id,
      "notes",
      trimmed ? { notes: trimmed } : { clear_notes: true },
    );
  }

  async function saveTags() {
    const parsedTags = parseTags(tags);
    await props.onPatch(
      props.item.item_id,
      "tags",
      parsedTags.length ? { tags: parsedTags } : { clear_tags: true },
    );
  }

  async function handleDelete() {
    const confirmed = window.confirm(
      `Remove ${props.item.name} from the selected inventory?`,
    );
    if (!confirmed) {
      return;
    }
    await props.onDelete(props.item.item_id, props.item.name);
  }

  const isBusy = props.busyAction !== null;
  const parsedQuantity = Number.parseInt(quantity, 10);
  const quantityIsValid = Number.isInteger(parsedQuantity) && parsedQuantity > 0;
  const quantityHasError =
    quantity.trim() !== String(props.item.quantity) && !quantityIsValid;
  const quantityDirty = quantityIsValid && parsedQuantity !== props.item.quantity;
  const finishDirty = finish !== props.item.finish;
  const locationDirty =
    normalizeOptionalText(location) !== normalizeOptionalText(props.item.location);
  const notesDirty =
    normalizeOptionalText(notes) !== normalizeOptionalText(props.item.notes);
  const currentTags = parseTags(tags);
  const tagsDirty = !equalStringArrays(currentTags, props.item.tags);
  const hasDirtyChanges =
    quantityDirty || finishDirty || locationDirty || notesDirty || tagsDirty;
  const busyMessage = props.busyAction ? getBusyMessage(props.busyAction) : null;
  const statusMessage = busyMessage
    ? busyMessage
    : quantityHasError
      ? "Enter a whole-number quantity greater than 0."
      : hasDirtyChanges
        ? "Unsaved changes"
        : "All changes saved";

  return (
    <article className={isBusy ? "owned-card owned-card-busy" : "owned-card"}>
      <div className="card-hero">
        <CardThumbnail
          imageUrl={props.item.image_uri_small}
          imageUrlLarge={props.item.image_uri_normal}
          name={props.item.name}
          variant="owned"
        />

        <div className="card-hero-body">
          <div className="owned-card-header">
            <div>
              <h3>{props.item.name}</h3>
              <p className="result-card-subtitle">
                {props.item.set_name} · #{props.item.collector_number}
              </p>
              <p className={busyMessage ? "row-status-label row-status-busy" : quantityHasError ? "row-status-label row-status-error" : hasDirtyChanges ? "row-status-label row-status-dirty" : "row-status-label row-status-ready"}>
                {statusMessage}
              </p>
            </div>
            <div className="owned-card-pricing">
              <strong>{formatUsd(decimalToNumber(props.item.est_value))}</strong>
              <span>{props.item.price_date || "No price date"}</span>
            </div>
          </div>

          <div className="tag-row">
            <span className="tag-chip">{props.item.set_code.toUpperCase()}</span>
            <span className="tag-chip subdued">{props.item.condition_code}</span>
            <span className="tag-chip subdued">{formatFinishLabel(props.item.finish)}</span>
            <span className="tag-chip subdued">{formatLanguageCode(props.item.language_code)}</span>
          </div>
        </div>
      </div>

      <div className="item-meta-grid">
        <MetaLine
          label="Unit price"
          value={formatMaybeCurrency(props.item.unit_price, props.item.currency)}
        />
        <MetaLine
          label="Acquisition"
          value={formatMaybeCurrency(
            props.item.acquisition_price,
            props.item.acquisition_currency,
          )}
        />
        <MetaLine
          label="Location"
          value={props.item.location || "Not set"}
        />
        <MetaLine
          label="Saved note"
          value={props.item.notes ? summarizeInlineText(props.item.notes, 40) : "No saved notes"}
        />
      </div>

      <div className="editor-section-header">
        <strong>Inline edits</strong>
        <span>{hasDirtyChanges ? "Save the highlighted changes below" : "Adjust any field below"}</span>
      </div>

      <div className="editor-grid">
        <InlineEditor
          dirty={quantityDirty}
          invalid={quantityHasError}
          disabled={isBusy || !quantityDirty}
          busy={props.busyAction === "quantity"}
          label="Quantity"
          onSave={saveQuantity}
        >
          <input
            className="text-input"
            disabled={isBusy}
            min="1"
            onChange={(event) => setQuantity(event.target.value)}
            type="number"
            value={quantity}
          />
        </InlineEditor>

        <InlineEditor
          dirty={finishDirty}
          disabled={isBusy || !finishDirty}
          busy={props.busyAction === "finish"}
          label="Finish"
          onSave={saveFinish}
        >
          <select
            className="text-input"
            disabled={isBusy}
            onChange={(event) => setFinish(event.target.value as FinishValue)}
            value={finish}
          >
            {FINISH_OPTIONS.map((option) => (
              <option
                key={option.value}
                value={option.value}
              >
                {option.label}
              </option>
            ))}
          </select>
        </InlineEditor>

        <InlineEditor
          dirty={locationDirty}
          disabled={isBusy || !locationDirty}
          busy={props.busyAction === "location"}
          label="Location"
          onSave={saveLocation}
        >
          <input
            className="text-input"
            disabled={isBusy}
            onChange={(event) => setLocation(event.target.value)}
            placeholder="Row location"
            value={location}
          />
        </InlineEditor>

        <InlineEditor
          dirty={tagsDirty}
          disabled={isBusy || !tagsDirty}
          busy={props.busyAction === "tags"}
          label="Tags"
          onSave={saveTags}
        >
          <input
            className="text-input"
            disabled={isBusy}
            onChange={(event) => setTags(event.target.value)}
            placeholder="burn, trade"
            value={tags}
          />
        </InlineEditor>
      </div>

      <InlineEditor
        dirty={notesDirty}
        disabled={isBusy || !notesDirty}
        busy={props.busyAction === "notes"}
        label="Notes"
        onSave={saveNotes}
        wide
      >
        <textarea
          className="text-area"
          disabled={isBusy}
          onChange={(event) => setNotes(event.target.value)}
          rows={3}
          value={notes}
        />
      </InlineEditor>

      <div className="owned-card-footer">
        <div className="tag-row">
          {props.item.tags.length ? (
            props.item.tags.map((tag) => (
              <span
                className="tag-chip"
                key={tag}
              >
                {tag}
              </span>
            ))
          ) : (
            <span className="muted-note">No tags</span>
          )}
        </div>
        <button
          className="danger-button"
          disabled={isBusy}
          onClick={() => {
            void handleDelete();
          }}
          type="button"
        >
          {props.busyAction === "delete" ? "Removing..." : "Remove row"}
        </button>
      </div>
    </article>
  );
}

function InlineEditor(props: {
  label: string;
  children: ReactNode;
  onSave: () => Promise<void>;
  busy?: boolean;
  dirty?: boolean;
  invalid?: boolean;
  disabled?: boolean;
  wide?: boolean;
}) {
  const className = props.wide
    ? props.dirty
      ? "field inline-editor inline-editor-dirty wide"
      : "field inline-editor wide"
    : props.dirty
      ? "field inline-editor inline-editor-dirty"
      : "field inline-editor";

  return (
    <label className={className}>
      <span>{props.label}</span>
      <div className="inline-editor-row">
        {props.children}
        <button
          className="secondary-button"
          disabled={props.disabled}
          onClick={() => {
            void props.onSave();
          }}
          type="button"
        >
          {props.busy
            ? "Saving..."
            : props.invalid
              ? "Fix value"
              : props.dirty
                ? "Save"
                : "Saved"}
        </button>
      </div>
    </label>
  );
}

function PanelState(props: {
  title: string;
  body: string;
  variant?: "idle" | "loading" | "error";
  compact?: boolean;
}) {
  const variant = props.variant || "idle";
  const className = props.compact
    ? `empty-state compact-empty state-block state-${variant}`
    : `empty-state state-block state-${variant}`;

  return (
    <div className={className}>
      <div className="state-block-header">
        {variant === "loading" ? <span className="state-pulse" aria-hidden="true" /> : null}
        <strong>{props.title}</strong>
      </div>
      <p>{props.body}</p>
    </div>
  );
}

function CardThumbnail(props: {
  imageUrl: string | null;
  imageUrlLarge: string | null;
  name: string;
  variant: "search" | "owned";
}) {
  const [didFail, setDidFail] = useState(false);

  useEffect(() => {
    setDidFail(false);
  }, [props.imageUrl]);

  const hasImage = Boolean(props.imageUrl) && !didFail;
  const className = `card-thumb card-thumb-${props.variant}`;

  return (
    <div className={className}>
      {hasImage ? (
        <img
          alt={`${props.name} card art`}
          className="card-thumb-image"
          decoding="async"
          loading="lazy"
          onError={() => setDidFail(true)}
          src={props.imageUrl || undefined}
        />
      ) : (
        <div className="card-thumb-fallback">
          <span>Card Art</span>
          <strong>{props.imageUrlLarge ? "Preview unavailable" : "No image data"}</strong>
        </div>
      )}
    </div>
  );
}

function MetaLine(props: { label: string; value: string }) {
  return (
    <div className="meta-line">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

function parseTags(value: string) {
  return value
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean)
    .filter((tag, index, tags) => tags.indexOf(tag) === index);
}

function decimalToNumber(value: string | null) {
  if (!value) {
    return 0;
  }
  return Number.parseFloat(value);
}

function formatUsd(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value || 0);
}

function formatMaybeCurrency(value: string | null, currency: string | null) {
  if (!value) {
    return "Not set";
  }
  if (currency === "USD" || !currency) {
    return formatUsd(decimalToNumber(value));
  }
  return `${value} ${currency}`;
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function toUserMessage(error: unknown, fallback: string) {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function resolveSelectedInventorySlug(
  inventories: InventorySummary[],
  preferredSlug: string | null,
) {
  if (preferredSlug && inventories.some((inventory) => inventory.slug === preferredSlug)) {
    return preferredSlug;
  }

  return inventories[0]?.slug ?? null;
}

function getBusyMessage(action: ItemMutationAction) {
  switch (action) {
    case "quantity":
      return "Saving quantity...";
    case "finish":
      return "Saving finish...";
    case "location":
      return "Saving location...";
    case "notes":
      return "Saving notes...";
    case "tags":
      return "Saving tags...";
    case "delete":
      return "Removing row...";
  }
}

function normalizeOptionalText(value: string | null | undefined) {
  const text = value?.trim();
  return text ? text : null;
}

function equalStringArrays(left: string[], right: string[]) {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((value, index) => value === right[index]);
}

function getInventoryCollectionEmptyMessage(inventory: InventorySummary) {
  if (inventory.total_cards === 0) {
    const lead = inventory.description
      ? `${inventory.description}.`
      : `${inventory.display_name} is ready for its first card.`;
    return `${lead} Search for a card and add it to create the first owned row.`;
  }

  return "Add a card from the search panel to create the first owned row.";
}

function getInventoryAuditEmptyMessage(inventory: InventorySummary) {
  if (inventory.total_cards === 0) {
    return "This inventory has not recorded any write activity yet. Adding the first card will start the audit trail.";
  }

  return "Once you add, edit, or remove cards, the latest events will appear here.";
}

function formatStatusLabel(status: AsyncStatus) {
  switch (status) {
    case "idle":
      return "Waiting";
    case "loading":
      return "Loading";
    case "ready":
      return "Ready";
    case "error":
      return "Error";
  }
}

function formatFinishLabel(value: FinishInput | string) {
  if (value === "nonfoil") {
    return "Normal";
  }
  return FINISH_OPTIONS.find((option) => option.value === value)?.label || value;
}

function formatLanguageCode(value: string) {
  return value.toUpperCase();
}

function formatAuditAction(value: string) {
  return value
    .split("_")
    .map((part) => formatTitleCase(part))
    .join(" ");
}

function formatAuditActor(event: InventoryAuditEvent) {
  if (event.actor_id && event.actor_id !== event.actor_type) {
    return `${event.actor_id} via ${formatActorType(event.actor_type)}`;
  }
  return event.actor_id || formatActorType(event.actor_type);
}

function summarizeInlineText(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength - 1)}…`;
}

function getPatchSuccessMessage(
  response: InventoryItemPatchResponse,
  inventoryLabel: string,
) {
  switch (response.operation) {
    case "set_quantity":
      return `Updated ${response.card_name} to quantity ${response.quantity} in ${inventoryLabel}.`;
    case "set_finish":
      return `Set ${response.card_name} to ${formatFinishLabel(response.finish)} in ${inventoryLabel}.`;
    case "set_location":
      return response.merged
        ? `Updated location for ${response.card_name} and merged matching rows in ${inventoryLabel}.`
        : `Updated location for ${response.card_name} to ${formatLocationLabel(response.location)} in ${inventoryLabel}.`;
    case "set_condition":
      return response.merged
        ? `Updated condition for ${response.card_name} and merged matching rows in ${inventoryLabel}.`
        : `Set condition for ${response.card_name} to ${response.condition_code} in ${inventoryLabel}.`;
    case "set_notes":
      return response.notes
        ? `Saved notes for ${response.card_name} in ${inventoryLabel}.`
        : `Cleared notes for ${response.card_name} in ${inventoryLabel}.`;
    case "set_tags":
      return response.tags.length
        ? `Saved ${response.tags.length} tag${response.tags.length === 1 ? "" : "s"} for ${response.card_name} in ${inventoryLabel}.`
        : `Cleared tags for ${response.card_name} in ${inventoryLabel}.`;
    case "set_acquisition":
      return response.acquisition_price
        ? `Updated acquisition details for ${response.card_name} in ${inventoryLabel}.`
        : `Cleared acquisition details for ${response.card_name} in ${inventoryLabel}.`;
  }
}

function formatLocationLabel(value: string | null) {
  return value?.trim() ? value : "no location";
}

function formatTitleCase(value: string) {
  if (!value) {
    return value;
  }

  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatActorType(value: string) {
  if (value.toLowerCase() === "api") {
    return "API";
  }
  return formatTitleCase(value);
}
