import { useEffect, useState } from "react";
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
  InventoryAuditEvent,
  InventorySummary,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
} from "./types";

const FINISH_OPTIONS = [
  { value: "normal", label: "Normal" },
  { value: "foil", label: "Foil" },
  { value: "etched", label: "Etched" },
];

type AsyncStatus = "idle" | "loading" | "ready" | "error";

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
  const [busyItemId, setBusyItemId] = useState<number | null>(null);
  const [busyAddCardId, setBusyAddCardId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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
        setSelectedInventory((current) => {
          if (current && nextInventories.some((inventory) => inventory.slug === current)) {
            return current;
          }
          return nextInventories[0]?.slug ?? null;
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
      setItems([]);
      setAuditEvents([]);
      setViewStatus("idle");
      return;
    }

    const inventorySlug: string = selectedInventory;

    let cancelled = false;

    async function loadInventoryView() {
      setViewStatus("loading");
      setViewError(null);

      try {
        const [nextItems, nextAuditEvents] = await Promise.all([
          listInventoryItems(inventorySlug),
          listInventoryAudit(inventorySlug),
        ]);
        if (cancelled) {
          return;
        }
        setItems(nextItems);
        setAuditEvents(nextAuditEvents);
        setViewStatus("ready");
      } catch (error) {
        if (cancelled) {
          return;
        }
        setViewError(
          toUserMessage(
            error,
            `Could not load collection data for '${inventorySlug}'.`,
          ),
        );
        setViewStatus("error");
      }
    }

    void loadInventoryView();

    return () => {
      cancelled = true;
    };
  }, [selectedInventory]);

  async function refreshInventoryOverview(options: { reloadInventories?: boolean } = {}) {
    if (!selectedInventory) {
      return;
    }

    setViewStatus("loading");

    const refreshTasks = [
      listInventoryItems(selectedInventory).then((nextItems) => {
        setItems(nextItems);
      }),
      listInventoryAudit(selectedInventory).then((nextAuditEvents) => {
        setAuditEvents(nextAuditEvents);
      }),
    ];

    if (options.reloadInventories) {
      refreshTasks.push(
        listInventories().then((nextInventories) => {
          setInventories(nextInventories);
        }),
      );
    }

    await Promise.all(refreshTasks);
    setViewStatus("ready");
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
    if (!selectedInventory) {
      return;
    }

    setBusyAddCardId(payload.scryfall_id);
    setNotice(null);

    try {
      await addInventoryItem(selectedInventory, payload);
      await refreshInventoryOverview({ reloadInventories: true });
      setNotice("Card added to the selected inventory.");
    } catch (error) {
      setNotice(toUserMessage(error, "Could not add the card."));
    } finally {
      setBusyAddCardId(null);
    }
  }

  async function handlePatchItem(
    itemId: number,
    payload: PatchInventoryItemRequest,
    successMessage: string,
  ) {
    if (!selectedInventory) {
      return;
    }

    setBusyItemId(itemId);
    setNotice(null);

    try {
      await patchInventoryItem(selectedInventory, itemId, payload);
      await refreshInventoryOverview({ reloadInventories: true });
      setNotice(successMessage);
    } catch (error) {
      setNotice(toUserMessage(error, "Could not save the change."));
    } finally {
      setBusyItemId(null);
    }
  }

  async function handleDeleteItem(itemId: number, cardName: string) {
    if (!selectedInventory) {
      return;
    }

    setBusyItemId(itemId);
    setNotice(null);

    try {
      await deleteInventoryItem(selectedInventory, itemId);
      await refreshInventoryOverview({ reloadInventories: true });
      setNotice(`Removed ${cardName} from the selected inventory.`);
    } catch (error) {
      setNotice(toUserMessage(error, "Could not remove the card."));
    } finally {
      setBusyItemId(null);
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
            A contract-first frontend scaffold for the local inventory demo. It
            already matches today&apos;s HTTP API and keeps the open backend
            requests isolated behind the client layer.
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

      {notice ? <div className="notice-banner">{notice}</div> : null}

      <div className="workspace-grid">
        <aside className="sidebar-column">
          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Collection Scope</p>
                <h2>Inventories</h2>
              </div>
              <span className={`status-pill status-${inventoryStatus}`}>
                {inventoryStatus}
              </span>
            </div>

            {inventoryError ? <p className="panel-error">{inventoryError}</p> : null}

            <div className="inventory-nav">
              {inventories.length ? (
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
                    <span className="inventory-button-title">
                      {inventory.display_name}
                    </span>
                    <span className="inventory-button-meta">
                      {inventory.total_cards} cards
                    </span>
                  </button>
                ))
              ) : (
                <div className="empty-state compact-empty">
                  <p>No inventories are available yet.</p>
                </div>
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="section-kicker">Recent Activity</p>
                <h2>Audit Feed</h2>
              </div>
              <span className="muted-note">Latest 12 events</span>
            </div>

            {viewError ? <p className="panel-error">{viewError}</p> : null}

            <div className="audit-list">
              {auditEvents.length ? (
                auditEvents.map((event) => (
                  <article
                    className="audit-card"
                    key={event.id}
                  >
                    <div className="audit-card-topline">
                      <span className="audit-action">{event.action}</span>
                      <span className="audit-time">
                        {formatTimestamp(event.occurred_at)}
                      </span>
                    </div>
                    <p className="audit-meta">
                      Actor: {event.actor_id || event.actor_type}
                    </p>
                    <p className="audit-meta">
                      Item: {event.item_id ? `#${event.item_id}` : "inventory"}
                    </p>
                  </article>
                ))
              ) : (
                <div className="empty-state compact-empty">
                  <p>No audit events yet for this inventory.</p>
                </div>
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

            {searchError ? <p className="panel-error">{searchError}</p> : null}

            <div className="search-results-grid">
              {searchResults.length ? (
                searchResults.map((result) => (
                  <SearchResultCard
                    busy={busyAddCardId === result.scryfall_id}
                    key={result.scryfall_id}
                    onAdd={handleAddCard}
                    result={result}
                  />
                ))
              ) : (
                <div className="empty-state">
                  <p>
                    {searchStatus === "ready"
                      ? "No search results yet. Try a different card name."
                      : "Run a search to populate the add-card workflow."}
                  </p>
                </div>
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
                {viewStatus}
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

            {viewError ? <p className="panel-error">{viewError}</p> : null}

            <div className="collection-grid">
              {items.length ? (
                items.map((item) => (
                  <OwnedItemCard
                    busy={busyItemId === item.item_id}
                    item={item}
                    key={item.item_id}
                    onDelete={handleDeleteItem}
                    onPatch={handlePatchItem}
                  />
                ))
              ) : (
                <div className="empty-state">
                  <p>This inventory is empty. Add a card from the search panel.</p>
                </div>
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
  onAdd: (payload: AddInventoryItemRequest) => Promise<void>;
}) {
  const [quantity, setQuantity] = useState("1");
  const [finish, setFinish] = useState(props.result.finishes[0] || "normal");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const parsedQuantity = Number.parseInt(quantity, 10);
    if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) {
      return;
    }

    await props.onAdd({
      scryfall_id: props.result.scryfall_id,
      quantity: parsedQuantity,
      finish,
      location: location.trim(),
      notes: notes.trim() || null,
      tags: parseTags(tags),
    });
  }

  const availableFinishes = FINISH_OPTIONS.filter((option) =>
    props.result.finishes.includes(option.value),
  );

  return (
    <article className="result-card">
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
            {value}
          </span>
        ))}
      </div>

      <form
        className="add-card-form"
        onSubmit={handleSubmit}
      >
        <div className="mini-grid">
          <label className="field">
            <span>Qty</span>
            <input
              className="text-input"
              min="1"
              onChange={(event) => setQuantity(event.target.value)}
              type="number"
              value={quantity}
            />
          </label>

          <label className="field">
            <span>Finish</span>
            <select
              className="text-input"
              onChange={(event) => setFinish(event.target.value)}
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

        <label className="field">
          <span>Location</span>
          <input
            className="text-input"
            onChange={(event) => setLocation(event.target.value)}
            placeholder="Red Binder"
            value={location}
          />
        </label>

        <label className="field">
          <span>Tags</span>
          <input
            className="text-input"
            onChange={(event) => setTags(event.target.value)}
            placeholder="burn, trade"
            value={tags}
          />
        </label>

        <label className="field">
          <span>Notes</span>
          <textarea
            className="text-area"
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Optional add-note for the row"
            rows={3}
            value={notes}
          />
        </label>

        <button
          className="primary-button"
          disabled={props.busy}
          type="submit"
        >
          {props.busy ? "Adding..." : "Add to inventory"}
        </button>
      </form>
    </article>
  );
}

function OwnedItemCard(props: {
  item: OwnedInventoryRow;
  busy: boolean;
  onPatch: (
    itemId: number,
    payload: PatchInventoryItemRequest,
    successMessage: string,
  ) => Promise<void>;
  onDelete: (itemId: number, cardName: string) => Promise<void>;
}) {
  const [quantity, setQuantity] = useState(String(props.item.quantity));
  const [finish, setFinish] = useState(props.item.finish);
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
    const parsedQuantity = Number.parseInt(quantity, 10);
    if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) {
      return;
    }
    await props.onPatch(
      props.item.item_id,
      { quantity: parsedQuantity },
      `Updated quantity for ${props.item.name}.`,
    );
  }

  async function saveFinish() {
    await props.onPatch(
      props.item.item_id,
      { finish },
      `Updated finish for ${props.item.name}.`,
    );
  }

  async function saveLocation() {
    const trimmed = location.trim();
    await props.onPatch(
      props.item.item_id,
      trimmed ? { location: trimmed } : { clear_location: true },
      `Updated location for ${props.item.name}.`,
    );
  }

  async function saveNotes() {
    const trimmed = notes.trim();
    await props.onPatch(
      props.item.item_id,
      trimmed ? { notes: trimmed } : { clear_notes: true },
      `Updated notes for ${props.item.name}.`,
    );
  }

  async function saveTags() {
    const parsedTags = parseTags(tags);
    await props.onPatch(
      props.item.item_id,
      parsedTags.length ? { tags: parsedTags } : { clear_tags: true },
      `Updated tags for ${props.item.name}.`,
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

  return (
    <article className={props.busy ? "owned-card owned-card-busy" : "owned-card"}>
      <div className="owned-card-header">
        <div>
          <h3>{props.item.name}</h3>
          <p className="result-card-subtitle">
            {props.item.set_name} · #{props.item.collector_number}
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
        <span className="tag-chip subdued">{props.item.finish}</span>
        <span className="tag-chip subdued">{props.item.language_code}</span>
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
      </div>

      <div className="editor-grid">
        <InlineEditor
          label="Quantity"
          onSave={saveQuantity}
        >
          <input
            className="text-input"
            disabled={props.busy}
            min="1"
            onChange={(event) => setQuantity(event.target.value)}
            type="number"
            value={quantity}
          />
        </InlineEditor>

        <InlineEditor
          label="Finish"
          onSave={saveFinish}
        >
          <select
            className="text-input"
            disabled={props.busy}
            onChange={(event) => setFinish(event.target.value)}
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
          label="Location"
          onSave={saveLocation}
        >
          <input
            className="text-input"
            disabled={props.busy}
            onChange={(event) => setLocation(event.target.value)}
            placeholder="Row location"
            value={location}
          />
        </InlineEditor>

        <InlineEditor
          label="Tags"
          onSave={saveTags}
        >
          <input
            className="text-input"
            disabled={props.busy}
            onChange={(event) => setTags(event.target.value)}
            placeholder="burn, trade"
            value={tags}
          />
        </InlineEditor>
      </div>

      <InlineEditor
        label="Notes"
        onSave={saveNotes}
        wide
      >
        <textarea
          className="text-area"
          disabled={props.busy}
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
          disabled={props.busy}
          onClick={() => {
            void handleDelete();
          }}
          type="button"
        >
          {props.busy ? "Working..." : "Remove row"}
        </button>
      </div>
    </article>
  );
}

function InlineEditor(props: {
  label: string;
  children: ReactNode;
  onSave: () => Promise<void>;
  wide?: boolean;
}) {
  return (
    <label className={props.wide ? "field inline-editor wide" : "field inline-editor"}>
      <span>{props.label}</span>
      <div className="inline-editor-row">
        {props.children}
        <button
          className="secondary-button"
          onClick={() => {
            void props.onSave();
          }}
          type="button"
        >
          Save
        </button>
      </div>
    </label>
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
