import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent as ReactKeyboardEvent } from "react";

import {
  addInventoryItem,
  listInventories,
  listInventoryAudit,
  listInventoryItems,
  patchInventoryItem,
  deleteInventoryItem,
  searchCards,
} from "./api";
import { ActivityDrawer } from "./components/ActivityDrawer";
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

const AUTOCOMPLETE_MIN_QUERY_LENGTH = 2;
const AUTOCOMPLETE_DEBOUNCE_MS = 250;
const AUTOCOMPLETE_LIMIT = 5;

export default function App() {
  const [inventories, setInventories] = useState<InventorySummary[]>([]);
  const [selectedInventory, setSelectedInventory] = useState<string | null>(null);
  const [items, setItems] = useState<OwnedInventoryRow[]>([]);
  const [auditEvents, setAuditEvents] = useState<InventoryAuditEvent[]>([]);
  const [inventoryStatus, setInventoryStatus] = useState<AsyncStatus>("loading");
  const [viewStatus, setViewStatus] = useState<AsyncStatus>("idle");
  const [searchStatus, setSearchStatus] = useState<AsyncStatus>("idle");
  const [suggestionStatus, setSuggestionStatus] = useState<AsyncStatus>("idle");
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("Lightning Bolt");
  const [searchResults, setSearchResults] = useState<CatalogSearchRow[]>([]);
  const [suggestionResults, setSuggestionResults] = useState<CatalogSearchRow[]>([]);
  const [suggestionOpen, setSuggestionOpen] = useState(false);
  const [highlightedSuggestionIndex, setHighlightedSuggestionIndex] = useState(-1);
  const [busyItem, setBusyItem] = useState<ItemMutationState | null>(null);
  const [busyAddCardId, setBusyAddCardId] = useState<string | null>(null);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [collectionView, setCollectionView] = useState<"compact" | "table" | "detailed">("compact");
  const [expandedItemId, setExpandedItemId] = useState<number | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<number[]>([]);
  const [activityOpen, setActivityOpen] = useState(false);
  const [finishSupportByCard, setFinishSupportByCard] = useState<Record<string, FinishSupportState>>({});
  const selectedInventoryRef = useRef<string | null>(null);
  const inventoryViewRequestIdRef = useRef(0);
  const finishLookupRequestIdRef = useRef(0);
  const suggestionLookupRequestIdRef = useRef(0);
  const suggestionCacheRef = useRef<Record<string, CatalogSearchRow[]>>({});
  const skipSuggestionFetchQueryRef = useRef<string | null>(null);

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
      setExpandedItemId(null);
      setSelectedItemIds([]);
      setActivityOpen(false);
      setViewError(null);
      setViewStatus("idle");
      return;
    }

    setExpandedItemId(null);
    setSelectedItemIds([]);
    void loadInventoryOverview(selectedInventory);
  }, [selectedInventory]);

  useEffect(() => {
    const visibleItemIds = new Set(items.map((item) => item.item_id));
    setSelectedItemIds((current) => current.filter((itemId) => visibleItemIds.has(itemId)));
  }, [items]);

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

      void searchCards({
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

  function closeSuggestionList() {
    setSuggestionOpen(false);
    setHighlightedSuggestionIndex(-1);
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

    suggestionLookupRequestIdRef.current += 1;
    closeSuggestionList();

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

  async function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runCardSearch(searchQuery);
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

  function handleSearchInputKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
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
          void handleSuggestionSelect(activeSuggestion);
        }
        break;
      }
    }
  }

  async function handleSuggestionSelect(result: CatalogSearchRow) {
    const query = result.name.trim();
    skipSuggestionFetchQueryRef.current = query.toLowerCase();
    setSearchQuery(query);
    closeSuggestionList();
    await runCardSearch(query);
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

  function handleCollectionViewChange(nextView: "compact" | "table" | "detailed") {
    setCollectionView(nextView);
    if (nextView !== "compact") {
      setExpandedItemId(null);
    }
  }

  function handleToggleItemSelection(itemId: number) {
    setSelectedItemIds((current) =>
      current.includes(itemId)
        ? current.filter((existingItemId) => existingItemId !== itemId)
        : [...current, itemId],
    );
  }

  function handleSelectAllVisibleItems() {
    setSelectedItemIds(items.map((item) => item.item_id));
  }

  function handleClearSelectedItems() {
    setSelectedItemIds([]);
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
        </aside>

        <main className="content-column">
          <SearchPanel
            busyAddCardId={busyAddCardId}
            onAdd={handleAddCard}
            onNotice={reportNotice}
            onSearchFieldFocus={handleSearchFieldFocus}
            onSearchInputKeyDown={handleSearchInputKeyDown}
            onSearchQueryChange={handleSearchQueryChange}
            onSearchSubmit={handleSearchSubmit}
            onSuggestionHighlight={setHighlightedSuggestionIndex}
            onSuggestionRequestClose={handleSuggestionRequestClose}
            onSuggestionSelect={handleSuggestionSelect}
            searchError={searchError}
            searchQuery={searchQuery}
            searchResults={searchResults}
            searchStatus={searchStatus}
            selectedInventoryRow={selectedInventoryRow}
            suggestionError={suggestionError}
            suggestionOpen={suggestionOpen}
            suggestionResults={suggestionResults}
            suggestionStatus={suggestionStatus}
            highlightedSuggestionIndex={highlightedSuggestionIndex}
          />
          <OwnedCollectionPanel
            busyItem={busyItem}
            collectionView={collectionView}
            expandedItemId={expandedItemId}
            finishSupportByCard={finishSupportByCard}
            items={items}
            onClearSelectedItems={handleClearSelectedItems}
            onCollectionViewChange={handleCollectionViewChange}
            onDelete={handleDeleteItem}
            onExpandedItemChange={setExpandedItemId}
            onOpenActivity={() => setActivityOpen(true)}
            onNotice={reportNotice}
            onPatch={handlePatchItem}
            onSelectAllVisibleItems={handleSelectAllVisibleItems}
            onToggleItemSelection={handleToggleItemSelection}
            selectedInventoryRow={selectedInventoryRow}
            selectedItemIds={selectedItemIds}
            viewError={viewError}
            viewStatus={viewStatus}
          />
        </main>
      </div>

      <ActivityDrawer
        isOpen={activityOpen}
        onClose={() => setActivityOpen(false)}
        subtitle={
          selectedInventoryRow
            ? `${selectedInventoryRow.display_name} · latest 12 events`
            : "Choose an inventory to inspect its recent write activity."
        }
        title="Inventory Activity"
      >
        <AuditFeed
          auditEvents={auditEvents}
          embedded
          selectedInventoryRow={selectedInventoryRow}
          viewError={viewError}
          viewStatus={viewStatus}
        />
      </ActivityDrawer>
    </div>
  );
}
