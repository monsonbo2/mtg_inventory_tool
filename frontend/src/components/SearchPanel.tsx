import { useEffect, useId, useRef, useState } from "react";
import type {
  AddInventoryItemRequest,
  CatalogNameSearchRow,
  CatalogPrintingLookupRow,
  CatalogScope,
  InventoryCreateRequest,
  InventorySummary,
} from "../types";
import {
  summarizeSearchGroup,
  type SearchCardGroup,
} from "../searchResultHelpers";
import {
  normalizeInventorySlugInput,
  normalizeOptionalText,
  normalizeTagInputText,
} from "../uiHelpers";
import type { AsyncStatus, InventoryCreateResult, NoticeTone } from "../uiTypes";
import { SearchAutocomplete } from "./SearchAutocomplete";
import { PanelState } from "./ui/PanelState";
import { ModalDialog } from "./ui/ModalDialog";
import { SearchResultCard } from "./SearchResultCard";
import { CardThumbnail } from "./ui/CardThumbnail";

function getSuggestionStatusMessage(state: SearchPanelState) {
  const trimmedQuery = state.search.query.trim();
  if (trimmedQuery.length < 2) {
    return "Type at least 2 characters to load card suggestions.";
  }

  if (state.suggestions.status === "loading") {
    return "Loading card suggestions.";
  }

  if (state.suggestions.status === "error") {
    return state.suggestions.error || "Card suggestions are unavailable right now.";
  }

  if (state.suggestions.results.length) {
    return `${state.suggestions.results.length} card suggestion${
      state.suggestions.results.length === 1 ? "" : "s"
    } available. Use the arrow keys to review and press Enter to select one.`;
  }

  if (state.suggestions.status === "ready") {
    return "No card suggestions available. Press Search cards to run the full results view.";
  }

  return "Card suggestions are hidden.";
}

export type SearchPanelState = {
  selectedInventoryRow: InventorySummary | null;
  inventories: InventorySummary[];
  activeSearchGroupId: string | null;
  busyAddCardId: string | null;
  searchResultsVisible: boolean;
  searchWorkspaceMode: "browse" | "focus";
  search: {
    canLoadMore: boolean;
    error: string | null;
    groups: SearchCardGroup[];
    hiddenResultCount: number;
    loadedHiddenResultCount: number;
    isLoadingMore: boolean;
    isResultStale: boolean;
    loadMoreError: string | null;
    query: string;
    resultQuery: string;
    resultScope: CatalogScope;
    scope: CatalogScope;
    status: AsyncStatus;
    totalCount: number;
  };
  suggestions: {
    error: string | null;
    highlightedIndex: number;
    isOpen: boolean;
    results: CatalogNameSearchRow[];
    status: AsyncStatus;
  };
};

export type SearchPanelActions = {
  onSearchQueryChange: (value: string) => void;
  onSearchFieldFocus: () => void;
  onSearchInputKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  onSearchGroupSelect: (groupId: string) => void;
  onSearchResultsLoadMore: () => void;
  onSearchScopeChange: (scope: CatalogScope) => void;
  onSearchResultsDismiss: () => void;
  onSearchSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  onSearchWorkspaceBrowse: () => void;
  onCreateInventory: (
    payload: InventoryCreateRequest,
  ) => Promise<InventoryCreateResult>;
  onImportCsv: (
    file: Blob,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) => Promise<boolean>;
  onImportDeckUrl: (
    sourceUrl: string,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) => Promise<boolean>;
  onImportDecklist: (
    deckText: string,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) => Promise<boolean>;
  onLoadPrintings: (
    group: SearchCardGroup,
    options?: { includeAllLanguages?: boolean },
  ) => Promise<CatalogPrintingLookupRow[]>;
  onSuggestionHighlight: (index: number) => void;
  onSuggestionRequestClose: () => void;
  onSuggestionSelect: (result: CatalogNameSearchRow) => void;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
};

type ImportDialogMode = "url" | "text" | "csv";
type ImportTargetMode = "existing" | "create";

export function SearchPanel(props: {
  actions: SearchPanelActions;
  state: SearchPanelState;
}) {
  const searchFieldRef = useRef<HTMLLabelElement | null>(null);
  const importMenuRef = useRef<HTMLDivElement | null>(null);
  const searchResultRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const searchResultsPanelRef = useRef<HTMLDivElement | null>(null);
  const searchWorkspaceDetailRef = useRef<HTMLDivElement | null>(null);
  const searchWorkspaceRef = useRef<HTMLDivElement | null>(null);
  const autocompleteListId = useId();
  const autocompleteStatusId = `${autocompleteListId}-status`;
  const [importMenuOpen, setImportMenuOpen] = useState(false);
  const [activeImportDialog, setActiveImportDialog] = useState<ImportDialogMode | null>(null);
  const [importTargetMode, setImportTargetMode] = useState<ImportTargetMode>("existing");
  const [importTargetInventorySlug, setImportTargetInventorySlug] = useState<string | null>(
    props.state.selectedInventoryRow?.slug ?? props.state.inventories[0]?.slug ?? null,
  );
  const [importUrl, setImportUrl] = useState("");
  const [importDeckText, setImportDeckText] = useState("");
  const [importCsvFile, setImportCsvFile] = useState<File | null>(null);
  const [createCollectionName, setCreateCollectionName] = useState("");
  const [createCollectionSlug, setCreateCollectionSlug] = useState("");
  const [createCollectionDescription, setCreateCollectionDescription] = useState("");
  const [createCollectionDefaultLocation, setCreateCollectionDefaultLocation] = useState("");
  const [createCollectionDefaultTags, setCreateCollectionDefaultTags] = useState("");
  const [createCollectionSlugTouched, setCreateCollectionSlugTouched] = useState(false);
  const [showCreateCollectionSlugField, setShowCreateCollectionSlugField] = useState(false);
  const [importFormError, setImportFormError] = useState<string | null>(null);
  const [importSubmitBusy, setImportSubmitBusy] = useState<ImportDialogMode | null>(null);
  const [searchResultsPanelHeight, setSearchResultsPanelHeight] = useState<number | null>(null);
  const [searchWorkspaceOverlayHeight, setSearchWorkspaceOverlayHeight] = useState(0);
  const hasSearchResults = props.state.search.groups.length > 0;
  const showSearchResults = props.state.searchResultsVisible && hasSearchResults;
  const showAutocomplete = props.state.suggestions.isOpen;
  const activeSearchGroup =
    props.state.search.groups.find((group) => group.groupId === props.state.activeSearchGroupId) ||
    props.state.search.groups[0] ||
    null;
  const showSearchMatches =
    showSearchResults &&
    props.state.searchWorkspaceMode === "browse" &&
    props.state.search.groups.length > 1;
  const searchQueryLabel =
    props.state.search.resultQuery || activeSearchGroup?.name || "Search";
  const searchResultCount = props.state.search.totalCount || props.state.search.groups.length;
  const searchResultCountLabel = `${searchResultCount} matching card${
    searchResultCount === 1 ? "" : "s"
  }`;
  const nextSearchMatchCount = Math.min(
    10,
    props.state.search.loadedHiddenResultCount > 0
      ? props.state.search.loadedHiddenResultCount
      : props.state.search.hiddenResultCount || 10,
  );
  const searchResultsLoadMoreLabel = props.state.search.isLoadingMore
    ? "Loading more matches..."
    : props.state.search.loadedHiddenResultCount > 0
      ? `Show ${nextSearchMatchCount} more of ${props.state.search.hiddenResultCount} additional matches`
      : `Load ${nextSearchMatchCount} more matches`;
  const activeSuggestionId =
    showAutocomplete && props.state.suggestions.highlightedIndex >= 0
      ? `${autocompleteListId}-option-${props.state.suggestions.highlightedIndex}`
      : undefined;
  const searchScopeLabel =
    props.state.search.resultScope === "all" ? "All catalog" : "Cards";
  const activeSearchScopeLabel =
    props.state.search.scope === "all" ? "All catalog" : "Cards";
  const trimmedDraftQuery = props.state.search.query.trim();
  const searchDraftNote =
    props.state.search.status === "loading"
      ? `Updating results for ${trimmedDraftQuery || "this search"} in ${activeSearchScopeLabel}.`
      : `Showing ${searchScopeLabel.toLowerCase()} results for "${searchQueryLabel}". Search to update.`;

  useEffect(() => {
    if (!props.state.suggestions.isOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (searchFieldRef.current?.contains(target)) {
        return;
      }
      props.actions.onSuggestionRequestClose();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [props.actions, props.state.suggestions.isOpen]);

  useEffect(() => {
    if (!importMenuOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (importMenuRef.current?.contains(target)) {
        return;
      }
      setImportMenuOpen(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [importMenuOpen]);

  useEffect(() => {
    const defaultInventorySlug =
      props.state.selectedInventoryRow?.slug ?? props.state.inventories[0]?.slug ?? null;
    setImportTargetInventorySlug((current) => {
      if (
        current &&
        props.state.inventories.some((inventory) => inventory.slug === current)
      ) {
        return current;
      }
      return defaultInventorySlug;
    });
    if (!props.state.inventories.length) {
      setImportTargetMode("create");
    }
  }, [props.state.inventories, props.state.selectedInventoryRow]);

  useEffect(() => {
    if (!showSearchMatches || !activeSearchGroup) {
      return;
    }

    const activeNode = searchResultRefs.current[activeSearchGroup.groupId];
    if (typeof activeNode?.scrollIntoView === "function") {
      activeNode.scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    const activeIndex = props.state.search.groups.findIndex(
      (group) => group.groupId === activeSearchGroup.groupId,
    );
    const nextGroup = props.state.search.groups[activeIndex + 1];
    const nextNode = nextGroup ? searchResultRefs.current[nextGroup.groupId] : null;
    if (typeof nextNode?.scrollIntoView === "function") {
      nextNode.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }, [activeSearchGroup, props.state.search.groups, showSearchMatches]);

  useEffect(() => {
    if (!showSearchMatches) {
      setSearchResultsPanelHeight(null);
      return;
    }

    function updateSearchResultsPanelHeight() {
      const resultsPanelNode = searchResultsPanelRef.current;
      const detailNode = searchWorkspaceDetailRef.current;
      if (!resultsPanelNode || !detailNode) {
        return;
      }

      const resultsRect = resultsPanelNode.getBoundingClientRect();
      const detailRect = detailNode.getBoundingClientRect();
      const isStackedLayout = Math.abs(resultsRect.top - detailRect.top) > 8;
      if (isStackedLayout) {
        setSearchResultsPanelHeight(null);
        return;
      }

      setSearchResultsPanelHeight(Math.max(0, Math.round(detailRect.height)));
    }

    updateSearchResultsPanelHeight();

    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            updateSearchResultsPanelHeight();
          });

    if (resizeObserver) {
      if (searchResultsPanelRef.current) {
        resizeObserver.observe(searchResultsPanelRef.current);
      }
      if (searchWorkspaceDetailRef.current) {
        resizeObserver.observe(searchWorkspaceDetailRef.current);
      }
    }

    window.addEventListener("resize", updateSearchResultsPanelHeight);
    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", updateSearchResultsPanelHeight);
    };
  }, [activeSearchGroup?.groupId, showSearchMatches]);

  useEffect(() => {
    if (!showSearchResults) {
      setSearchWorkspaceOverlayHeight(0);
      return;
    }

    function updateSearchWorkspaceOverlayHeight() {
      const workspaceNode = searchWorkspaceRef.current;
      if (!workspaceNode || window.innerWidth <= 820) {
        setSearchWorkspaceOverlayHeight(0);
        return;
      }

      setSearchWorkspaceOverlayHeight(
        Math.max(0, Math.round(workspaceNode.getBoundingClientRect().height)),
      );
    }

    updateSearchWorkspaceOverlayHeight();

    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            updateSearchWorkspaceOverlayHeight();
          });

    if (resizeObserver && searchWorkspaceRef.current) {
      resizeObserver.observe(searchWorkspaceRef.current);
    }

    window.addEventListener("resize", updateSearchWorkspaceOverlayHeight);
    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", updateSearchWorkspaceOverlayHeight);
    };
  }, [activeSearchGroup?.groupId, showSearchMatches, showSearchResults]);

  const searchPanelOpenStyle =
    showSearchResults && searchWorkspaceOverlayHeight > 0
      ? {
          ["--search-workspace-overlay-height" as string]: `${searchWorkspaceOverlayHeight}px`,
        }
      : undefined;

  function getDefaultImportTargetInventorySlug() {
    return props.state.selectedInventoryRow?.slug ?? props.state.inventories[0]?.slug ?? null;
  }

  function resetImportDialogState() {
    setImportTargetMode(getDefaultImportTargetInventorySlug() ? "existing" : "create");
    setImportTargetInventorySlug(getDefaultImportTargetInventorySlug());
    setImportUrl("");
    setImportDeckText("");
    setImportCsvFile(null);
    setCreateCollectionName("");
    setCreateCollectionSlug("");
    setCreateCollectionDescription("");
    setCreateCollectionDefaultLocation("");
    setCreateCollectionDefaultTags("");
    setCreateCollectionSlugTouched(false);
    setShowCreateCollectionSlugField(false);
    setImportFormError(null);
    setImportSubmitBusy(null);
  }

  function closeImportDialog(force = false) {
    if (importSubmitBusy && !force) {
      return;
    }
    setActiveImportDialog(null);
    resetImportDialogState();
  }

  function openImportDialog(mode: ImportDialogMode) {
    setImportMenuOpen(false);
    resetImportDialogState();
    setActiveImportDialog(mode);
  }

  function toggleImportMenu() {
    if (!props.state.inventories.length) {
      return;
    }
    setImportMenuOpen((current) => !current);
  }

  function handleCreateCollectionNameChange(value: string) {
    setCreateCollectionName(value);
    if (!createCollectionSlugTouched) {
      setCreateCollectionSlug(normalizeInventorySlugInput(value));
    }
    if (importFormError) {
      setImportFormError(null);
    }
  }

  function handleCreateCollectionSlugChange(value: string) {
    setCreateCollectionSlugTouched(true);
    setCreateCollectionSlug(normalizeInventorySlugInput(value));
    if (importFormError) {
      setImportFormError(null);
    }
  }

  function handleCreateCollectionDescriptionChange(value: string) {
    setCreateCollectionDescription(value);
    if (importFormError) {
      setImportFormError(null);
    }
  }

  function handleCreateCollectionDefaultLocationChange(value: string) {
    setCreateCollectionDefaultLocation(value);
    if (importFormError) {
      setImportFormError(null);
    }
  }

  function handleCreateCollectionDefaultTagsChange(value: string) {
    setCreateCollectionDefaultTags(value);
    if (importFormError) {
      setImportFormError(null);
    }
  }

  function handleImportTargetModeChange(nextMode: ImportTargetMode) {
    setImportTargetMode(nextMode);
    if (nextMode === "existing" && !importTargetInventorySlug) {
      setImportTargetInventorySlug(getDefaultImportTargetInventorySlug());
    }
    if (importFormError) {
      setImportFormError(null);
    }
  }

  function handleImportTargetInventoryChange(inventorySlug: string) {
    setImportTargetInventorySlug(inventorySlug);
    if (importFormError) {
      setImportFormError(null);
    }
  }

  async function resolveImportTargetInventory() {
    if (importTargetMode === "existing") {
      if (!importTargetInventorySlug) {
        setImportFormError("Choose a collection before importing.");
        return null;
      }

      return {
        inventorySlug: importTargetInventorySlug,
        inventoryLabel:
          props.state.inventories.find((inventory) => inventory.slug === importTargetInventorySlug)
            ?.display_name || null,
      };
    }

    const nextDisplayName = createCollectionName.trim();
    const nextSlug = normalizeInventorySlugInput(createCollectionSlug);
    const nextDefaultLocation = normalizeOptionalText(createCollectionDefaultLocation);
    const nextDefaultTags = normalizeTagInputText(createCollectionDefaultTags);

    if (!nextDisplayName) {
      setImportFormError("Enter a collection name before creating it.");
      return null;
    }

    if (!nextSlug) {
      setShowCreateCollectionSlugField(true);
      setImportFormError("Enter a short name using letters, numbers, or hyphens.");
      return null;
    }

    const createPayload: InventoryCreateRequest = {
      display_name: nextDisplayName,
      slug: nextSlug,
      description: normalizeOptionalText(createCollectionDescription),
    };
    if (nextDefaultLocation) {
      createPayload.default_location = nextDefaultLocation;
    }
    if (nextDefaultTags) {
      createPayload.default_tags = nextDefaultTags;
    }

    const createResult = await props.actions.onCreateInventory(createPayload);

    if (createResult.ok) {
      setImportTargetInventorySlug(createResult.inventory.slug);
      setImportTargetMode("existing");
      return {
        inventorySlug: createResult.inventory.slug,
        inventoryLabel: createResult.inventory.display_name,
      };
    }

    if (createResult.reason === "conflict") {
      setShowCreateCollectionSlugField(true);
      setImportFormError(
        "That collection name needs a different short name. Edit it below and try again.",
      );
    }
    return null;
  }

  async function handleImportUrlSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const sourceUrl = importUrl.trim();
    if (!sourceUrl) {
      setImportFormError("Enter a supported deck URL before importing.");
      return;
    }

    setImportFormError(null);
    setImportSubmitBusy("url");
    try {
      const importTarget = await resolveImportTargetInventory();
      if (!importTarget) {
        return;
      }

      const didImport = await props.actions.onImportDeckUrl(
        sourceUrl,
        importTarget.inventorySlug,
        importTarget.inventoryLabel,
      );
      if (didImport) {
        closeImportDialog(true);
      }
    } finally {
      setImportSubmitBusy(null);
    }
  }

  async function handleImportTextSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const deckText = importDeckText.trim();
    if (!deckText) {
      setImportFormError("Paste a card list before importing.");
      return;
    }

    setImportFormError(null);
    setImportSubmitBusy("text");
    try {
      const importTarget = await resolveImportTargetInventory();
      if (!importTarget) {
        return;
      }

      const didImport = await props.actions.onImportDecklist(
        deckText,
        importTarget.inventorySlug,
        importTarget.inventoryLabel,
      );
      if (didImport) {
        closeImportDialog(true);
      }
    } finally {
      setImportSubmitBusy(null);
    }
  }

  async function handleImportCsvSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!importCsvFile) {
      setImportFormError("Choose a CSV file before importing.");
      return;
    }

    setImportFormError(null);
    setImportSubmitBusy("csv");
    try {
      const importTarget = await resolveImportTargetInventory();
      if (!importTarget) {
        return;
      }

      const didImport = await props.actions.onImportCsv(
        importCsvFile,
        importTarget.inventorySlug,
        importTarget.inventoryLabel,
      );
      if (didImport) {
        closeImportDialog(true);
      }
    } finally {
      setImportSubmitBusy(null);
    }
  }

  function renderImportTargetFields() {
    return (
      <div className="form-section form-section-muted search-import-target">
        <div className="form-section-header">
          <strong>Destination</strong>
          <span>Choose where imported cards should go.</span>
        </div>

        <div className="search-import-target-mode">
          <button
            aria-pressed={importTargetMode === "existing"}
            className={
              importTargetMode === "existing"
                ? "secondary-button search-import-target-mode-button search-import-target-mode-button-active"
                : "secondary-button search-import-target-mode-button"
            }
            disabled={!props.state.inventories.length || Boolean(importSubmitBusy)}
            onClick={() => handleImportTargetModeChange("existing")}
            type="button"
          >
            Add to existing
          </button>
          <button
            aria-pressed={importTargetMode === "create"}
            className={
              importTargetMode === "create"
                ? "secondary-button search-import-target-mode-button search-import-target-mode-button-active"
                : "secondary-button search-import-target-mode-button"
            }
            disabled={Boolean(importSubmitBusy)}
            onClick={() => handleImportTargetModeChange("create")}
            type="button"
          >
            Create new
          </button>
        </div>

        {importTargetMode === "existing" ? (
          <div className="search-import-target-list">
            {props.state.inventories.map((inventory) => (
              <button
                key={inventory.slug}
                className={
                  importTargetInventorySlug === inventory.slug
                    ? "search-import-target-option search-import-target-option-active"
                    : "search-import-target-option"
                }
                disabled={Boolean(importSubmitBusy)}
                onClick={() => handleImportTargetInventoryChange(inventory.slug)}
                type="button"
              >
                <strong>{inventory.display_name}</strong>
                <span className="search-import-target-option-meta">
                  {inventory.item_rows} entr{inventory.item_rows === 1 ? "y" : "ies"} · {inventory.total_cards} cards
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="search-import-create-grid">
            <label className="field">
              <span>Collection name</span>
              <input
                className="text-input"
                disabled={Boolean(importSubmitBusy)}
                onChange={(event) => handleCreateCollectionNameChange(event.target.value)}
                placeholder="e.g. Trade Binder"
                value={createCollectionName}
              />
            </label>

            {showCreateCollectionSlugField ? (
              <label className="field">
                <span>Short name</span>
                <input
                  className="text-input"
                  disabled={Boolean(importSubmitBusy)}
                  onChange={(event) => handleCreateCollectionSlugChange(event.target.value)}
                  placeholder="demo-imports"
                  value={createCollectionSlug}
                />
                <span className="field-hint field-hint-info">
                  Used for links and quick references. Keep it short and easy to recognize.
                </span>
              </label>
            ) : null}

            <label className="field">
              <span>Description (optional)</span>
              <textarea
                className="text-area"
                disabled={Boolean(importSubmitBusy)}
                onChange={(event) => handleCreateCollectionDescriptionChange(event.target.value)}
                placeholder="Add a short description for this collection."
                value={createCollectionDescription}
              />
            </label>

            <label className="field">
              <span>Default location</span>
              <input
                className="text-input"
                disabled={Boolean(importSubmitBusy)}
                onChange={(event) =>
                  handleCreateCollectionDefaultLocationChange(event.target.value)
                }
                placeholder="e.g. Trade Binder"
                value={createCollectionDefaultLocation}
              />
              <span className="field-hint field-hint-info">
                Items added to this collection will automatically use this location unless
                you choose another one while adding cards.
              </span>
            </label>

            <label className="field">
              <span>Default tags</span>
              <input
                className="text-input"
                disabled={Boolean(importSubmitBusy)}
                onChange={(event) =>
                  handleCreateCollectionDefaultTagsChange(event.target.value)
                }
                placeholder="e.g. trade, staples"
                value={createCollectionDefaultTags}
              />
              <span className="field-hint field-hint-info">
                Items added to this collection will automatically include these tags.
              </span>
            </label>

            <p className="panel-hint inventory-sidebar-note">
              Collections help separate personal, trade, deck, and project cards.
            </p>
          </div>
        )}
      </div>
    );
  }

  return (
    <section
      className={
        showSearchResults
          ? "panel panel-featured search-panel search-panel-results-open"
          : "panel panel-featured search-panel"
      }
      style={searchPanelOpenStyle}
    >
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Search And Add</p>
          <h2>Card Search</h2>
        </div>
        <span className="muted-note">
          Current collection: {props.state.selectedInventoryRow?.display_name || "None"}
        </span>
      </div>

      <div className="search-panel-toolbar">
        <div className="search-import" ref={importMenuRef}>
          <button
            aria-expanded={importMenuOpen}
            aria-haspopup="menu"
            className="secondary-button search-import-trigger"
            disabled={!props.state.inventories.length}
            onClick={toggleImportMenu}
            type="button"
          >
            Import Cards
          </button>

          {importMenuOpen ? (
            <div aria-label="Import Cards" className="search-import-menu" role="menu">
              <button
                className="search-import-menu-option"
                onClick={() => openImportDialog("url")}
                role="menuitem"
                type="button"
              >
                <strong>Import from URL</strong>
                <span>Load a supported public deck link into the collection you choose.</span>
              </button>
              <button
                className="search-import-menu-option"
                onClick={() => openImportDialog("text")}
                role="menuitem"
                type="button"
              >
                <strong>Import as Text</strong>
                <span>Paste a decklist or card list into the collection you choose.</span>
              </button>
              <button
                className="search-import-menu-option"
                onClick={() => openImportDialog("csv")}
                role="menuitem"
                type="button"
              >
                <strong>Import from CSV</strong>
                <span>Upload a collection CSV file into the collection you choose.</span>
              </button>
            </div>
          ) : null}
        </div>
      </div>

      <form className="search-form" onSubmit={props.actions.onSearchSubmit}>
        <label className="field search-field" ref={searchFieldRef}>
          <span>Quick Add and Card Search</span>
          <div className="search-input-stack">
            <input
              aria-activedescendant={activeSuggestionId}
              aria-autocomplete="list"
              aria-controls={autocompleteListId}
              aria-describedby={autocompleteStatusId}
              aria-expanded={showAutocomplete}
              aria-haspopup="listbox"
              className="text-input"
              onChange={(event) => props.actions.onSearchQueryChange(event.target.value)}
              onClick={props.actions.onSearchFieldFocus}
              onFocus={props.actions.onSearchFieldFocus}
              onKeyDown={props.actions.onSearchInputKeyDown}
              placeholder="e.g. Lightning Bolt"
              role="combobox"
              value={props.state.search.query}
            />
            <SearchAutocomplete
              error={props.state.suggestions.error}
              highlightedIndex={props.state.suggestions.highlightedIndex}
              isOpen={showAutocomplete}
              listboxId={autocompleteListId}
              onHighlight={props.actions.onSuggestionHighlight}
              onSelect={props.actions.onSuggestionSelect}
              optionIdPrefix={autocompleteListId}
              query={props.state.search.query}
              results={props.state.suggestions.results}
              status={props.state.suggestions.status}
            />
          </div>
        </label>
        <div className="search-form-actions">
          <div
            aria-label="Catalog search scope"
            className="search-scope-toggle"
            role="group"
          >
            <button
              aria-pressed={props.state.search.scope === "default"}
              className={
                props.state.search.scope === "default"
                  ? "search-scope-option search-scope-option-active"
                  : "search-scope-option"
              }
              onClick={() => props.actions.onSearchScopeChange("default")}
              type="button"
            >
              Cards
            </button>
            <button
              aria-pressed={props.state.search.scope === "all"}
              className={
                props.state.search.scope === "all"
                  ? "search-scope-option search-scope-option-active"
                  : "search-scope-option"
              }
              onClick={() => props.actions.onSearchScopeChange("all")}
              type="button"
            >
              All catalog
            </button>
          </div>
          <button className="primary-button search-submit-button" type="submit">
            {props.state.search.status === "loading" ? "Searching..." : "Search cards"}
          </button>
        </div>
      </form>
      <p aria-live="polite" className="sr-only" id={autocompleteStatusId}>
        {getSuggestionStatusMessage(props.state)}
      </p>

      {!props.state.selectedInventoryRow ? (
        <p className="panel-hint">
          Search is available now. Choose a collection to enable add actions.
        </p>
      ) : props.state.selectedInventoryRow.total_cards === 0 ? (
        <p className="panel-hint panel-hint-success">
          {props.state.selectedInventoryRow.display_name} is ready for its first cards. Use search
          results below to get started.
        </p>
      ) : null}

      {props.state.search.status === "loading" && !hasSearchResults ? (
        <PanelState
          body="Looking through matching cards and printings."
          eyebrow="Search"
          title="Searching cards"
          variant="loading"
        />
      ) : props.state.search.status === "error" ? (
        <PanelState
          body="Card search is temporarily unavailable. Try again in a moment."
          eyebrow="Search"
          title="Search unavailable"
          variant="error"
        />
      ) : props.state.search.status === "ready" && !hasSearchResults ? (
        <PanelState
          body="Try a broader card name, a simpler spelling, or fewer extra terms."
          eyebrow="Search"
          title="No matching cards"
        />
      ) : null}

      {showSearchResults && activeSearchGroup ? (
        <div className="search-workspace" ref={searchWorkspaceRef}>
          <div className="search-workspace-header">
            <div className="search-workspace-header-copy">
              <p className="section-kicker">Search Results</p>
              <p className="search-workspace-title">{searchQueryLabel}</p>
              <p className="search-workspace-summary">
                {showSearchMatches
                  ? `${searchResultCountLabel} in ${searchScopeLabel}. Pick a card on the left, then confirm the printing and details on the right.`
                  : "Selected card ready. Confirm the printing and details below."}
              </p>
              {props.state.search.isResultStale ? (
                <p className="search-workspace-draft-note">{searchDraftNote}</p>
              ) : null}
            </div>
            <div className="search-workspace-header-actions">
              {props.state.search.groups.length > 1 ? (
                props.state.searchWorkspaceMode === "focus" ? (
                  <button
                    className="secondary-button search-workspace-toggle"
                    onClick={props.actions.onSearchWorkspaceBrowse}
                    type="button"
                  >
                    Back to matches
                  </button>
                ) : (
                  <span className="search-workspace-count">{searchResultCountLabel}</span>
                )
              ) : null}
              <button
                aria-label="Close add card pane"
                className="search-results-close"
                onClick={props.actions.onSearchResultsDismiss}
                type="button"
              >
                ×
              </button>
            </div>
          </div>

          <div
            className={
              showSearchMatches
                ? "search-workspace-grid"
                : "search-workspace-grid search-workspace-grid-focus"
            }
          >
            {showSearchMatches ? (
              <div
                className="search-workspace-results"
                ref={searchResultsPanelRef}
                style={
                  searchResultsPanelHeight
                    ? { height: `${searchResultsPanelHeight}px` }
                    : undefined
                }
              >
                <div className="search-workspace-results-header">
                  <strong>Matching cards</strong>
                  <span>Select a card to review printings.</span>
                </div>

                <div className="search-workspace-result-list">
                  {props.state.search.groups.map((group) => {
                    const isActive = group.groupId === activeSearchGroup.groupId;

                    return (
                    <button
                      aria-pressed={isActive}
                      className={
                        isActive
                          ? "search-workspace-result search-workspace-result-active"
                          : "search-workspace-result"
                      }
                      key={group.groupId}
                      onClick={() => props.actions.onSearchGroupSelect(group.groupId)}
                      ref={(node) => {
                        searchResultRefs.current[group.groupId] = node;
                      }}
                      type="button"
                    >
                        <CardThumbnail
                          imageUrl={group.image_uri_small}
                          imageUrlLarge={group.image_uri_normal}
                          name={group.name}
                          variant="search"
                        />
                        <span className="search-workspace-result-copy">
                          <strong>{group.name}</strong>
                          <span className="search-workspace-result-meta">
                            {group.printingsCount} printing{group.printingsCount === 1 ? "" : "s"}
                          </span>
                          <span className="search-workspace-result-summary">
                            {summarizeSearchGroup(group)}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>

                {props.state.search.canLoadMore ? (
                  <div className="search-workspace-results-footer">
                    {props.state.search.loadMoreError ? (
                      <p className="search-workspace-load-more-error" role="status">
                        {props.state.search.loadMoreError}
                      </p>
                    ) : null}
                    <button
                      className="secondary-button search-workspace-load-more"
                      disabled={props.state.search.isLoadingMore}
                      onClick={props.actions.onSearchResultsLoadMore}
                      type="button"
                    >
                      {searchResultsLoadMoreLabel}
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="search-workspace-detail" ref={searchWorkspaceDetailRef}>
              <SearchResultCard
                busyPrintingId={props.state.busyAddCardId}
                canAdd={Boolean(props.state.selectedInventoryRow)}
                defaultLocation={props.state.selectedInventoryRow?.default_location || null}
                defaultTags={props.state.selectedInventoryRow?.default_tags || null}
                group={activeSearchGroup}
                onAdd={props.actions.onAdd}
                onLoadPrintings={props.actions.onLoadPrintings}
                onNotice={props.actions.onNotice}
              />
            </div>
          </div>
        </div>
      ) : null}

      <ModalDialog
        isOpen={activeImportDialog === "url"}
        kicker="Import Cards"
        onClose={closeImportDialog}
        subtitle="Paste a supported public deck URL, then choose an existing collection or create a new one for the import."
        title="Import From URL"
      >
        <form className="search-import-form" onSubmit={handleImportUrlSubmit}>
          {renderImportTargetFields()}

          <label className="field">
            <span>Deck URL</span>
            <input
              className="text-input"
              data-autofocus
              disabled={Boolean(importSubmitBusy)}
              onChange={(event) => setImportUrl(event.target.value)}
              placeholder="https://www.moxfield.com/decks/..."
              value={importUrl}
            />
          </label>

          {importFormError ? <p className="field-hint field-hint-error">{importFormError}</p> : null}

          <div className="search-import-actions">
            <button className="primary-button" disabled={Boolean(importSubmitBusy)} type="submit">
              {importSubmitBusy === "url" ? "Importing..." : "Import cards"}
            </button>
            <button
              className="secondary-button"
              disabled={Boolean(importSubmitBusy)}
              onClick={() => closeImportDialog()}
              type="button"
            >
              Cancel
            </button>
          </div>
        </form>
      </ModalDialog>

      <ModalDialog
        isOpen={activeImportDialog === "text"}
        kicker="Import Cards"
        onClose={closeImportDialog}
        subtitle="Paste a decklist or card list, then choose an existing collection or create a new one for the import."
        title="Import As Text"
      >
        <form className="search-import-form" onSubmit={handleImportTextSubmit}>
          {renderImportTargetFields()}

          <label className="field">
            <span>Card list</span>
            <textarea
              className="text-area search-import-text-area"
              data-autofocus
              disabled={Boolean(importSubmitBusy)}
              onChange={(event) => setImportDeckText(event.target.value)}
              placeholder={"4 Lightning Bolt\n2 Counterspell\nSB: 3 Pyroblast"}
              value={importDeckText}
            />
          </label>

          {importFormError ? <p className="field-hint field-hint-error">{importFormError}</p> : null}

          <div className="search-import-actions">
            <button className="primary-button" disabled={Boolean(importSubmitBusy)} type="submit">
              {importSubmitBusy === "text" ? "Importing..." : "Import cards"}
            </button>
            <button
              className="secondary-button"
              disabled={Boolean(importSubmitBusy)}
              onClick={() => closeImportDialog()}
              type="button"
            >
              Cancel
            </button>
          </div>
        </form>
      </ModalDialog>

      <ModalDialog
        isOpen={activeImportDialog === "csv"}
        kicker="Import Cards"
        onClose={closeImportDialog}
        subtitle="Upload a collection CSV, then choose an existing collection or create a new one for the import."
        title="Import From CSV"
      >
        <form className="search-import-form" onSubmit={handleImportCsvSubmit}>
          {renderImportTargetFields()}

          <label className="field">
            <span>CSV file</span>
            <input
              accept=".csv,text/csv"
              className="search-import-file-input"
              data-autofocus
              disabled={Boolean(importSubmitBusy)}
              onChange={(event) => setImportCsvFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </label>

          {importFormError ? <p className="field-hint field-hint-error">{importFormError}</p> : null}

          <div className="search-import-actions">
            <button className="primary-button" disabled={Boolean(importSubmitBusy)} type="submit">
              {importSubmitBusy === "csv" ? "Importing..." : "Import cards"}
            </button>
            <button
              className="secondary-button"
              disabled={Boolean(importSubmitBusy)}
              onClick={() => closeImportDialog()}
              type="button"
            >
              Cancel
            </button>
          </div>
        </form>
      </ModalDialog>
    </section>
  );
}
