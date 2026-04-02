import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  addInventoryItem,
  listInventories,
  listInventoryAudit,
  listInventoryItems,
  patchInventoryItem,
  deleteInventoryItem,
  searchCards,
} from "./api";
import { AuditFeed } from "./components/AuditFeed";
import { InventorySidebar } from "./components/InventorySidebar";
import { OwnedCollectionPanel } from "./components/OwnedCollectionPanel";
import { SearchPanel } from "./components/SearchPanel";
import { MetricCard } from "./components/ui/MetricCard";
import { NoticeBanner } from "./components/ui/NoticeBanner";
import type {
  AddInventoryItemRequest,
  CatalogSearchRow,
  InventoryAuditEvent,
  InventorySummary,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
} from "./types";
import {
  decimalToNumber,
  formatUsd,
  getPatchSuccessMessage,
  getUniqueItemsByCardId,
  resolveSelectedInventorySlug,
  toUserMessage,
} from "./uiHelpers";
import type {
  AsyncStatus,
  FinishSupportState,
  ItemMutationAction,
  ItemMutationState,
  NoticeState,
  NoticeTone,
  ViewRefreshOutcome,
} from "./uiTypes";

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
  const [finishSupportByCard, setFinishSupportByCard] = useState<Record<string, FinishSupportState>>({});
  const selectedInventoryRef = useRef<string | null>(null);
  const inventoryViewRequestIdRef = useRef(0);
  const finishLookupRequestIdRef = useRef(0);

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
        setSelectedInventory((current) => resolveSelectedInventorySlug(nextInventories, current));
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

  useEffect(() => {
    const uniqueItems = getUniqueItemsByCardId(items);
    const itemsNeedingFinishSupport = uniqueItems.filter(
      (item) => finishSupportByCard[item.scryfall_id] === undefined,
    );

    if (!itemsNeedingFinishSupport.length) {
      return;
    }

    const requestId = ++finishLookupRequestIdRef.current;
    let cancelled = false;

    setFinishSupportByCard((current) => {
      const next = { ...current };
      for (const item of itemsNeedingFinishSupport) {
        if (next[item.scryfall_id] === undefined) {
          next[item.scryfall_id] = { status: "loading" };
        }
      }
      return next;
    });

    void Promise.all(
      itemsNeedingFinishSupport.map(async (item) => {
        try {
          const results = await searchCards({
            query: item.name,
            set_code: item.set_code,
            exact: true,
            limit: 8,
          });
          const match =
            results.find((result) => result.scryfall_id === item.scryfall_id) ??
            results.find(
              (result) =>
                result.set_code === item.set_code &&
                result.collector_number === item.collector_number,
            );

          if (!match) {
            return {
              cardId: item.scryfall_id,
              state: {
                status: "error",
                message:
                  "Could not verify legal finishes for this printing yet. Unsupported finish changes will still be rejected by the API.",
              } satisfies FinishSupportState,
            };
          }

          return {
            cardId: item.scryfall_id,
            state: {
              status: "ready",
              finishes: match.finishes,
            } satisfies FinishSupportState,
          };
        } catch (error) {
          return {
            cardId: item.scryfall_id,
            state: {
              status: "error",
              message: toUserMessage(
                error,
                "Could not verify legal finishes for this printing yet. Unsupported finish changes will still be rejected by the API.",
              ),
            } satisfies FinishSupportState,
          };
        }
      }),
    ).then((results) => {
      if (cancelled || requestId !== finishLookupRequestIdRef.current) {
        return;
      }

      setFinishSupportByCard((current) => {
        const next = { ...current };
        for (const result of results) {
          next[result.cardId] = result.state;
        }
        return next;
      });
    });

    return () => {
      cancelled = true;
    };
  }, [finishSupportByCard, items]);

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
        toUserMessage(error, `Could not load collection data for '${inventorySlug}'.`),
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
          <MetricCard accent="Sunrise" label="Inventories" value={String(inventories.length)} />
          <MetricCard accent="Lagoon" label="Rows In View" value={String(items.length)} />
          <MetricCard
            accent="Paper"
            label="Est. Value"
            value={formatUsd(totalEstimatedValue)}
          />
        </div>
      </header>

      {notice ? <NoticeBanner notice={notice} /> : null}

      <div className="workspace-grid">
        <aside className="sidebar-column">
          <InventorySidebar
            inventories={inventories}
            inventoryError={inventoryError}
            inventoryStatus={inventoryStatus}
            onSelectInventory={setSelectedInventory}
            selectedInventory={selectedInventory}
            selectedInventoryRow={selectedInventoryRow}
          />
          <AuditFeed
            auditEvents={auditEvents}
            selectedInventoryRow={selectedInventoryRow}
            viewError={viewError}
            viewStatus={viewStatus}
          />
        </aside>

        <main className="content-column">
          <SearchPanel
            busyAddCardId={busyAddCardId}
            onAdd={handleAddCard}
            onNotice={reportNotice}
            onSearchQueryChange={setSearchQuery}
            onSearchSubmit={handleSearchSubmit}
            searchError={searchError}
            searchQuery={searchQuery}
            searchResults={searchResults}
            searchStatus={searchStatus}
            selectedInventoryRow={selectedInventoryRow}
          />
          <OwnedCollectionPanel
            busyItem={busyItem}
            finishSupportByCard={finishSupportByCard}
            items={items}
            onDelete={handleDeleteItem}
            onNotice={reportNotice}
            onPatch={handlePatchItem}
            selectedInventoryRow={selectedInventoryRow}
            viewError={viewError}
            viewStatus={viewStatus}
          />
        </main>
      </div>
    </div>
  );
}
