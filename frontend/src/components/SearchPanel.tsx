import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  AddInventoryItemRequest,
  CatalogNameSearchRow,
  CatalogPrintingLookupRow,
  CatalogScope,
  CsvImportResolutionRequest,
  DeckUrlImportResolutionRequest,
  DecklistImportResolutionRequest,
  InventoryCreateRequest,
  InventorySummary,
} from "../types";
import {
  buildInitialInventoryImportResolutionSelectionMap,
  buildInventoryImportResolutionSelections,
  getInventoryImportResolutionProgress,
  reconcileInventoryImportResolutionSelectionMap,
  type InventoryImportResolutionSelectionMap,
} from "../importFlowHelpers";
import {
  summarizeSearchGroup,
  type SearchCardGroup,
} from "../searchResultHelpers";
import {
  normalizeInventorySlugInput,
  normalizeOptionalText,
  normalizeTagInputText,
} from "../uiHelpers";
import type {
  AsyncStatus,
  CsvImportSession,
  DeckUrlImportSession,
  DecklistImportSession,
  InventoryCreateResult,
  InventoryImportCommitResult,
  InventoryImportPreviewResult,
  InventoryImportSession,
  InventoryImportStep,
  NoticeTone,
  SearchAddAvailability,
} from "../uiTypes";
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

function measureSearchWorkspaceContentHeight(workspaceNode: HTMLDivElement) {
  const reserveNode = Array.from(workspaceNode.children).find(
    (child): child is HTMLElement =>
      child instanceof HTMLElement &&
      child.dataset.searchWorkspaceReserve === "true",
  );
  const reserveHeight = reserveNode?.getBoundingClientRect().height ?? 0;
  const workspaceHeight = workspaceNode.getBoundingClientRect().height;
  const workspaceScrollHeight = workspaceNode.scrollHeight;

  return Math.ceil(
    Math.max(
      0,
      Math.max(workspaceHeight, workspaceScrollHeight - reserveHeight),
    ),
  );
}

function getSearchResultPeekHeight(resultNode: HTMLElement | null) {
  if (!resultNode) {
    return 40;
  }

  return Math.min(48, Math.max(40, Math.round(resultNode.offsetHeight * 0.55)));
}

function scrollSearchResultListForActiveRow(options: {
  activeNode: HTMLButtonElement;
  adjacentNode: HTMLButtonElement | null;
  direction: "down" | "up" | null;
  listNode: HTMLDivElement;
}) {
  const { activeNode, adjacentNode, direction, listNode } = options;
  const maxScrollTop = Math.max(0, listNode.scrollHeight - listNode.clientHeight);
  if (maxScrollTop <= 0) {
    return;
  }

  const currentScrollTop = listNode.scrollTop;
  const activeTop = activeNode.offsetTop;
  const activeBottom = activeTop + activeNode.offsetHeight;
  const peekHeight = getSearchResultPeekHeight(adjacentNode);

  let nextScrollTop = currentScrollTop;
  const targetTop = direction === "up" ? Math.max(0, activeTop - peekHeight) : activeTop;
  const targetBottom =
    direction === "down"
      ? Math.min(listNode.scrollHeight, activeBottom + peekHeight)
      : activeBottom;

  if (targetBottom > currentScrollTop + listNode.clientHeight) {
    nextScrollTop = targetBottom - listNode.clientHeight;
  }

  if (targetTop < nextScrollTop) {
    nextScrollTop = targetTop;
  }

  nextScrollTop = Math.max(0, Math.min(maxScrollTop, Math.ceil(nextScrollTop)));
  if (Math.abs(nextScrollTop - currentScrollTop) < 1) {
    return;
  }

  if (typeof listNode.scrollTo === "function") {
    listNode.scrollTo({ top: nextScrollTop, behavior: "smooth" });
    return;
  }

  listNode.scrollTop = nextScrollTop;
}

export type SearchPanelState = {
  selectedInventoryRow: InventorySummary | null;
  selectedInventoryCanWrite: boolean;
  inventories: InventorySummary[];
  writableInventories: InventorySummary[];
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
  commitCsvImport: (
    session: CsvImportSession,
    resolutions?: CsvImportResolutionRequest[],
  ) => Promise<InventoryImportCommitResult>;
  commitDeckUrlImport: (
    session: DeckUrlImportSession,
    resolutions?: DeckUrlImportResolutionRequest[],
  ) => Promise<InventoryImportCommitResult>;
  commitDecklistImport: (
    session: DecklistImportSession,
    resolutions?: DecklistImportResolutionRequest[],
  ) => Promise<InventoryImportCommitResult>;
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
  previewCsvImport: (
    file: Blob,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) => Promise<InventoryImportPreviewResult>;
  previewDeckUrlImport: (
    sourceUrl: string,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) => Promise<InventoryImportPreviewResult>;
  previewDecklistImport: (
    deckText: string,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) => Promise<InventoryImportPreviewResult>;
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

function getImportDialogStepTitle(mode: ImportDialogMode) {
  switch (mode) {
    case "url":
      return "Import From URL";
    case "text":
      return "Import As Text";
    case "csv":
      return "Import From CSV";
  }
}

function getImportDialogStepSubtitle(
  mode: ImportDialogMode,
  step: InventoryImportStep | null,
) {
  if (step === "needs_resolution") {
    return "Review the preview, resolve the remaining import questions, and continue when every required entry is mapped.";
  }

  switch (mode) {
    case "url":
      return "Paste a supported public deck URL, then choose an existing collection or create a new one for the import.";
    case "text":
      return "Paste a decklist or card list, then choose an existing collection or create a new one for the import.";
    case "csv":
      return "Upload a collection CSV, then choose an existing collection or create a new one for the import.";
  }
}

function getInventoryImportModeForDialog(mode: ImportDialogMode) {
  switch (mode) {
    case "url":
      return "deck_url" as const;
    case "text":
      return "decklist" as const;
    case "csv":
      return "csv" as const;
  }
}

function getImportSourceSummary(session: InventoryImportSession) {
  switch (session.mode) {
    case "csv":
      return {
        label: "Source",
        value: session.source.file instanceof File ? session.source.file.name : session.preview.csv_filename,
        detail: `Detected as ${session.preview.detected_format.replaceAll("_", " ")}.`,
      };
    case "decklist":
      return {
        label: "Source",
        value: session.preview.deck_name || "Pasted card list",
        detail: `${session.preview.rows_seen} line${session.preview.rows_seen === 1 ? "" : "s"} reviewed.`,
      };
    case "deck_url":
      return {
        label: "Source",
        value: session.preview.deck_name || session.source.sourceUrl,
        detail: `${session.preview.provider} preview from ${session.preview.source_url}.`,
      };
  }
}

export function SearchPanel(props: {
  actions: SearchPanelActions;
  focusRequest?: { target: "search" | "import"; token: number } | null;
  importActionHost: HTMLElement | null;
  importActionHostEnabled: boolean;
  state: SearchPanelState;
}) {
  const searchPanelRef = useRef<HTMLElement | null>(null);
  const searchFieldRef = useRef<HTMLLabelElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const importTriggerRef = useRef<HTMLButtonElement | null>(null);
  const importMenuRef = useRef<HTMLDivElement | null>(null);
  const searchResultRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const searchResultsPanelRef = useRef<HTMLDivElement | null>(null);
  const searchResultListRef = useRef<HTMLDivElement | null>(null);
  const searchWorkspaceDetailRef = useRef<HTMLDivElement | null>(null);
  const searchWorkspaceGridRef = useRef<HTMLDivElement | null>(null);
  const searchWorkspaceHeaderRef = useRef<HTMLDivElement | null>(null);
  const searchWorkspaceRef = useRef<HTMLDivElement | null>(null);
  const searchQuickAddSectionRef = useRef<HTMLDivElement | null>(null);
  const searchPanelFlowHeightRef = useRef<number | null>(null);
  const searchWorkspaceOverlayKeyRef = useRef<string | null>(null);
  const searchWorkspaceOverlayWidthRef = useRef<number | null>(null);
  const searchWorkspaceGuidedSelectionRef = useRef<string | null>(null);
  const searchResultActiveIndexRef = useRef<number | null>(null);
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
  const [importSession, setImportSession] = useState<InventoryImportSession | null>(null);
  const [importResolutionSelections, setImportResolutionSelections] =
    useState<InventoryImportResolutionSelectionMap>({});
  const [importSubmitBusy, setImportSubmitBusy] = useState<ImportDialogMode | null>(null);
  const [searchResultsPanelHeight, setSearchResultsPanelHeight] = useState<number | null>(null);
  const [searchWorkspaceOverlay, setSearchWorkspaceOverlay] = useState({
    gridHeight: 0,
    headerHeight: 0,
    height: 0,
    panelOffsetHeight: 0,
    reserveHeight: 0,
  });
  const hasSearchResults = props.state.search.groups.length > 0;
  const existingImportTargetInventories = props.state.writableInventories;
  const hasExistingImportTargets = existingImportTargetInventories.length > 0;
  const activeImportMode = activeImportDialog
    ? getInventoryImportModeForDialog(activeImportDialog)
    : null;
  const activeImportSession =
    importSession && activeImportMode && importSession.mode === activeImportMode
      ? importSession
      : null;
  const importResolutionProgress =
    activeImportSession?.step === "needs_resolution"
      ? getInventoryImportResolutionProgress(
          activeImportSession,
          importResolutionSelections,
        )
      : null;
  const importResolutionCanContinue =
    importResolutionProgress !== null &&
    importResolutionProgress.blockedCount === 0 &&
    importResolutionProgress.selectedCount === importResolutionProgress.requiredCount;
  const urlImportNeedsResolution =
    activeImportSession?.mode === "deck_url" && activeImportSession.step === "needs_resolution";
  const textImportNeedsResolution =
    activeImportSession?.mode === "decklist" && activeImportSession.step === "needs_resolution";
  const csvImportNeedsResolution =
    activeImportSession?.mode === "csv" && activeImportSession.step === "needs_resolution";
  const selectedInventoryAddAvailability: SearchAddAvailability =
    !props.state.selectedInventoryRow
      ? "unselected"
      : props.state.selectedInventoryCanWrite
        ? "writable"
        : "read_only";
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
  const searchWorkspaceOverlayKey =
    props.state.search.resultQuery ||
    [
      props.state.search.resultScope,
      props.state.search.totalCount,
      props.state.search.groups.map((group) => group.groupId).join("|"),
    ].join(":");
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
    if (!props.focusRequest) {
      return;
    }

    const targetNode =
      props.focusRequest.target === "import"
        ? importTriggerRef.current
        : searchInputRef.current;
    if (!targetNode) {
      return;
    }

    if (typeof targetNode.scrollIntoView === "function") {
      targetNode.scrollIntoView({ block: "center", inline: "nearest" });
    }
    targetNode.focus();
  }, [props.focusRequest]);

  useEffect(() => {
    const defaultInventorySlug = getDefaultImportTargetInventorySlug();
    setImportTargetInventorySlug((current) => {
      if (
        current &&
        existingImportTargetInventories.some((inventory) => inventory.slug === current)
      ) {
        return current;
      }
      return defaultInventorySlug;
    });
    if (!hasExistingImportTargets) {
      setImportTargetMode("create");
    }
  }, [
    existingImportTargetInventories,
    hasExistingImportTargets,
    props.state.selectedInventoryCanWrite,
    props.state.selectedInventoryRow,
  ]);

  useEffect(() => {
    if (!showSearchMatches || !activeSearchGroup) {
      searchResultActiveIndexRef.current = null;
      return;
    }

    const resultListNode = searchResultListRef.current;
    const activeNode = searchResultRefs.current[activeSearchGroup.groupId];
    const activeIndex = props.state.search.groups.findIndex(
      (group) => group.groupId === activeSearchGroup.groupId,
    );
    const previousIndex = searchResultActiveIndexRef.current;
    const direction =
      previousIndex === null || previousIndex === activeIndex
        ? null
        : activeIndex > previousIndex
          ? "down"
          : "up";
    const adjacentIndex =
      direction === "up"
        ? activeIndex - 1
        : activeIndex + 1 < props.state.search.groups.length
          ? activeIndex + 1
          : -1;
    const adjacentNode =
      adjacentIndex >= 0
        ? searchResultRefs.current[props.state.search.groups[adjacentIndex]?.groupId ?? ""]
        : null;

    if (resultListNode && activeNode) {
      scrollSearchResultListForActiveRow({
        activeNode,
        adjacentNode,
        direction,
        listNode: resultListNode,
      });
    }

    searchResultActiveIndexRef.current = activeIndex;
  }, [activeSearchGroup, props.state.search.groups, showSearchMatches]);

  useEffect(() => {
    if (!showSearchResults || props.state.searchWorkspaceMode !== "focus") {
      searchWorkspaceGuidedSelectionRef.current = null;
    }
  }, [props.state.searchWorkspaceMode, showSearchResults]);

  useEffect(() => {
    if (
      !showSearchResults ||
      props.state.searchWorkspaceMode !== "focus" ||
      !activeSearchGroup ||
      typeof window === "undefined" ||
      window.innerWidth <= 820
    ) {
      return;
    }

    const guideKey = `${activeSearchGroup.groupId}:${searchWorkspaceOverlayKey}`;
    if (searchWorkspaceGuidedSelectionRef.current === guideKey) {
      return;
    }

    let frameId = 0;
    let nestedFrameId = 0;

    frameId = window.requestAnimationFrame(() => {
      nestedFrameId = window.requestAnimationFrame(() => {
        const workspaceNode = searchWorkspaceRef.current;
        const quickAddNode = searchQuickAddSectionRef.current;
        if (!workspaceNode || !quickAddNode) {
          return;
        }

        const workspaceRect = workspaceNode.getBoundingClientRect();
        const quickAddRect = quickAddNode.getBoundingClientRect();
        if (workspaceRect.height <= 0 || quickAddRect.height <= 0) {
          return;
        }

        const desiredQuickAddTop = 36;
        const desiredQuickAddBottomInset = 32;
        const desiredPageTop = 32;
        const desiredPageBottomInset = 32;
        const visibleTopBoundary = Math.max(
          workspaceRect.top + desiredQuickAddTop,
          desiredPageTop,
        );
        const visibleBottomBoundary = Math.min(
          workspaceRect.bottom - desiredQuickAddBottomInset,
          window.innerHeight - desiredPageBottomInset,
        );
        const availableQuickAddViewportHeight = Math.max(
          0,
          visibleBottomBoundary - visibleTopBoundary,
        );
        const visibleQuickAddTop = Math.max(quickAddRect.top, visibleTopBoundary);
        const visibleQuickAddBottom = Math.min(quickAddRect.bottom, visibleBottomBoundary);
        const visibleQuickAddHeight = Math.max(
          0,
          visibleQuickAddBottom - visibleQuickAddTop,
        );
        const desiredVisibleQuickAddHeight = Math.min(
          quickAddRect.height,
          availableQuickAddViewportHeight,
        );

        if (visibleQuickAddHeight >= desiredVisibleQuickAddHeight - 8) {
          searchWorkspaceGuidedSelectionRef.current = guideKey;
          return;
        }

        if (typeof quickAddNode.scrollIntoView === "function") {
          quickAddNode.scrollIntoView({
            behavior: "smooth",
            block: "start",
            inline: "nearest",
          });
        }
        searchWorkspaceGuidedSelectionRef.current = guideKey;
      });
    });

    return () => {
      window.cancelAnimationFrame(frameId);
      window.cancelAnimationFrame(nestedFrameId);
    };
  }, [
    activeSearchGroup?.groupId,
    props.state.searchWorkspaceMode,
    searchWorkspaceOverlay.headerHeight,
    searchWorkspaceOverlay.height,
    searchWorkspaceOverlayKey,
    showSearchResults,
  ]);

  useLayoutEffect(() => {
    if (showSearchResults) {
      return;
    }

    const panelNode = searchPanelRef.current;
    if (!panelNode) {
      return;
    }

    searchPanelFlowHeightRef.current = Math.ceil(
      panelNode.getBoundingClientRect().height,
    );
  }, [showSearchResults]);

  useLayoutEffect(() => {
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

  useLayoutEffect(() => {
    if (!showSearchResults) {
      searchWorkspaceOverlayKeyRef.current = null;
      searchWorkspaceOverlayWidthRef.current = null;
      setSearchWorkspaceOverlay({
        gridHeight: 0,
        headerHeight: 0,
        height: 0,
        panelOffsetHeight: 0,
        reserveHeight: 0,
      });
      return;
    }

    function updateSearchWorkspaceOverlayHeight() {
      const workspaceNode = searchWorkspaceRef.current;
      if (!workspaceNode || window.innerWidth <= 820) {
        searchWorkspaceOverlayWidthRef.current = window.innerWidth;
        setSearchWorkspaceOverlay({
          gridHeight: 0,
          headerHeight: 0,
          height: 0,
          panelOffsetHeight: 0,
          reserveHeight: 0,
        });
        return;
      }

      if (showSearchMatches) {
        const resultsPanelNode = searchResultsPanelRef.current;
        const detailNode = searchWorkspaceDetailRef.current;
        if (resultsPanelNode && detailNode) {
          const resultsRect = resultsPanelNode.getBoundingClientRect();
          const detailRect = detailNode.getBoundingClientRect();
          const isStackedLayout = Math.abs(resultsRect.top - detailRect.top) > 8;
          if (!isStackedLayout && searchResultsPanelHeight === null) {
            return;
          }
        }
      }

      const overlayKey = searchWorkspaceOverlayKey;
      const viewportWidth = window.innerWidth;
      const measuredHeight = Math.max(
        0,
        measureSearchWorkspaceContentHeight(workspaceNode),
      );
      const measuredHeaderHeight = Math.ceil(
        searchWorkspaceHeaderRef.current?.getBoundingClientRect().height ?? 0,
      );
      const measuredGridHeight = Math.ceil(
        searchWorkspaceGridRef.current?.getBoundingClientRect().height ?? 0,
      );
      const measuredPanelHeight = Math.ceil(
        searchPanelRef.current?.getBoundingClientRect().height ?? 0,
      );
      const targetPanelFlowHeight =
        searchPanelFlowHeightRef.current ??
        Math.max(0, measuredPanelHeight - measuredHeight);
      const shouldResetOverlayHeight =
        searchWorkspaceOverlayKeyRef.current !== overlayKey ||
        searchWorkspaceOverlayWidthRef.current !== viewportWidth;

      searchWorkspaceOverlayKeyRef.current = overlayKey;
      searchWorkspaceOverlayWidthRef.current = viewportWidth;
      setSearchWorkspaceOverlay((currentOverlay) => {
        const reservedHeight =
          shouldResetOverlayHeight || showSearchMatches || currentOverlay.height <= 0
            ? measuredHeight
            : Math.max(currentOverlay.height, measuredHeight);
        const reserveHeight = Math.max(0, reservedHeight - measuredHeight);
        const panelOffsetHeight = Math.max(
          0,
          measuredPanelHeight - targetPanelFlowHeight,
        );
        const headerHeight =
          shouldResetOverlayHeight ||
          showSearchMatches ||
          currentOverlay.headerHeight <= 0
            ? measuredHeaderHeight
            : currentOverlay.headerHeight;
        const gridHeight =
          shouldResetOverlayHeight ||
          showSearchMatches ||
          currentOverlay.gridHeight <= 0
            ? measuredGridHeight
            : currentOverlay.gridHeight;

        if (
          currentOverlay.height === reservedHeight &&
          currentOverlay.reserveHeight === reserveHeight &&
          currentOverlay.panelOffsetHeight === panelOffsetHeight &&
          currentOverlay.headerHeight === headerHeight &&
          currentOverlay.gridHeight === gridHeight
        ) {
          return currentOverlay;
        }

        return {
          gridHeight,
          headerHeight,
          height: reservedHeight,
          panelOffsetHeight,
          reserveHeight,
        };
      });
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
  }, [
    activeSearchGroup?.groupId,
    searchWorkspaceOverlayKey,
    searchResultsPanelHeight,
    showSearchMatches,
    showSearchResults,
  ]);

  const searchPanelOpenStyle =
    showSearchResults && searchWorkspaceOverlay.height > 0
      ? {
          ["--search-workspace-overlay-height" as string]: `${searchWorkspaceOverlay.height}px`,
          ...(searchWorkspaceOverlay.panelOffsetHeight > 0
            ? {
                ["--search-panel-overlay-offset" as string]: `${searchWorkspaceOverlay.panelOffsetHeight}px`,
              }
            : null),
          ...(searchWorkspaceOverlay.headerHeight > 0
            ? {
                ["--search-workspace-header-height" as string]: `${searchWorkspaceOverlay.headerHeight}px`,
              }
            : null),
          ...(searchWorkspaceOverlay.gridHeight > 0
            ? {
                ["--search-workspace-grid-height" as string]: `${searchWorkspaceOverlay.gridHeight}px`,
              }
            : null),
        }
      : undefined;

  function getDefaultImportTargetInventorySlug() {
    if (props.state.selectedInventoryCanWrite && props.state.selectedInventoryRow) {
      return props.state.selectedInventoryRow.slug;
    }
    return existingImportTargetInventories[0]?.slug ?? null;
  }

  function startImportResolutionSession(nextSession: InventoryImportSession) {
    setImportSession(nextSession);
    setImportResolutionSelections(
      buildInitialInventoryImportResolutionSelectionMap(nextSession),
    );
  }

  function updateImportResolutionSession(nextSession: InventoryImportSession) {
    setImportSession(nextSession);
    setImportResolutionSelections((currentSelections) =>
      reconcileInventoryImportResolutionSelectionMap(nextSession, currentSelections),
    );
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
    setImportSession(null);
    setImportResolutionSelections({});
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

  function handleImportResolutionSelectionChange(issueKey: string, optionKey: string) {
    setImportResolutionSelections((current) => ({
      ...current,
      [issueKey]: optionKey,
    }));
    if (importFormError) {
      setImportFormError(null);
    }
  }

  function handleImportBackToEdit() {
    setImportSession(null);
    setImportResolutionSelections({});
    setImportFormError(null);
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

  function renderImportAction(options: {
    placement: "hero" | "inline";
  }) {
    return (
      <div
        className={
          options.placement === "hero"
            ? "search-import workspace-hero-import"
            : "search-import"
        }
        ref={importMenuRef}
      >
        <button
          aria-expanded={importMenuOpen}
          aria-haspopup="menu"
          className={
            options.placement === "hero"
              ? "secondary-button search-import-trigger workspace-hero-import-trigger"
              : "utility-button search-import-trigger"
          }
          disabled={!props.state.inventories.length}
          onClick={toggleImportMenu}
          ref={importTriggerRef}
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
    );
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
          existingImportTargetInventories.find(
            (inventory) => inventory.slug === importTargetInventorySlug,
          )?.display_name || null,
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

  async function commitResolvedImport(
    session: InventoryImportSession,
    dialogMode: ImportDialogMode,
  ) {
    const progress = getInventoryImportResolutionProgress(
      session,
      importResolutionSelections,
    );
    if (progress.blockedCount > 0) {
      setImportFormError(
        "Some unresolved entries still do not have selectable matches, so this import cannot continue yet.",
      );
      return;
    }

    const resolutionSelections = buildInventoryImportResolutionSelections(
      session,
      importResolutionSelections,
    );
    if (!resolutionSelections) {
      const missingCount = Math.max(0, progress.requiredCount - progress.selectedCount);
      setImportFormError(
        missingCount === 1
          ? "Choose a match for the remaining unresolved entry before continuing."
          : `Choose matches for the remaining ${missingCount} unresolved entries before continuing.`,
      );
      return;
    }

    setImportFormError(null);
    setImportSubmitBusy(dialogMode);
    try {
      let result: InventoryImportCommitResult;
      switch (session.mode) {
        case "csv":
          result = await props.actions.commitCsvImport(session, resolutionSelections.mode === "csv" ? resolutionSelections.resolutions : []);
          break;
        case "decklist":
          result = await props.actions.commitDecklistImport(
            session,
            resolutionSelections.mode === "decklist" ? resolutionSelections.resolutions : [],
          );
          break;
        case "deck_url":
          result = await props.actions.commitDeckUrlImport(
            session,
            resolutionSelections.mode === "deck_url" ? resolutionSelections.resolutions : [],
          );
          break;
      }

      if (result.ok) {
        closeImportDialog(true);
        return;
      }

      if (result.reason === "still_needs_resolution" && result.session) {
        updateImportResolutionSession(result.session);
      }
    } finally {
      setImportSubmitBusy(null);
    }
  }

  async function handlePreviewResult(previewResult: InventoryImportPreviewResult) {
    if (!previewResult.ok) {
      return;
    }

    if (previewResult.session.step === "needs_resolution") {
      setImportFormError(null);
      startImportResolutionSession(previewResult.session);
      return;
    }

    let commitResult: InventoryImportCommitResult;
    switch (previewResult.session.mode) {
      case "csv":
        commitResult = await props.actions.commitCsvImport(previewResult.session);
        break;
      case "decklist":
        commitResult = await props.actions.commitDecklistImport(previewResult.session);
        break;
      case "deck_url":
        commitResult = await props.actions.commitDeckUrlImport(previewResult.session);
        break;
    }

    if (commitResult.ok) {
      closeImportDialog(true);
      return;
    }

    if (commitResult.reason === "still_needs_resolution" && commitResult.session) {
      updateImportResolutionSession(commitResult.session);
      return;
    }
  }

  async function handleImportUrlSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (activeImportSession?.mode === "deck_url" && activeImportSession.step === "needs_resolution") {
      await commitResolvedImport(activeImportSession, "url");
      return;
    }

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

      await handlePreviewResult(
        await props.actions.previewDeckUrlImport(
          sourceUrl,
          importTarget.inventorySlug,
          importTarget.inventoryLabel,
        ),
      );
    } finally {
      setImportSubmitBusy(null);
    }
  }

  async function handleImportTextSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (activeImportSession?.mode === "decklist" && activeImportSession.step === "needs_resolution") {
      await commitResolvedImport(activeImportSession, "text");
      return;
    }

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

      await handlePreviewResult(
        await props.actions.previewDecklistImport(
          deckText,
          importTarget.inventorySlug,
          importTarget.inventoryLabel,
        ),
      );
    } finally {
      setImportSubmitBusy(null);
    }
  }

  async function handleImportCsvSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (activeImportSession?.mode === "csv" && activeImportSession.step === "needs_resolution") {
      await commitResolvedImport(activeImportSession, "csv");
      return;
    }

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

      await handlePreviewResult(
        await props.actions.previewCsvImport(
          importCsvFile,
          importTarget.inventorySlug,
          importTarget.inventoryLabel,
        ),
      );
    } finally {
      setImportSubmitBusy(null);
    }
  }

  function renderImportResolutionStep(session: InventoryImportSession) {
    const resolutionProgress = getInventoryImportResolutionProgress(
      session,
      importResolutionSelections,
    );
    const importSourceSummary = getImportSourceSummary(session);
    const unresolvedCount = session.preview.summary.unresolved_card_quantity;
    const requestedCount = session.preview.summary.requested_card_quantity;
    const rowsMatched = session.preview.rows_written;

    return (
      <>
        <div className="search-import-preview">
          <div className="form-section search-import-preview-summary">
            <div className="form-section-header">
              <strong>Preview summary</strong>
              <span>
                {resolutionProgress.requiredCount === 1
                  ? "1 entry still needs a match before import can continue."
                  : `${resolutionProgress.requiredCount} entries still need matches before import can continue.`}
              </span>
            </div>
            <div className="search-import-preview-grid">
              <div className="search-import-preview-card">
                <span className="search-import-preview-label">
                  {importSourceSummary.label}
                </span>
                <strong>{importSourceSummary.value}</strong>
                <span>{importSourceSummary.detail}</span>
              </div>
              <div className="search-import-preview-card">
                <span className="search-import-preview-label">Destination</span>
                <strong>{session.inventoryLabel || session.inventorySlug}</strong>
                <span>Cards will land in this collection after the import completes.</span>
              </div>
              <div className="search-import-preview-card">
                <span className="search-import-preview-label">Requested cards</span>
                <strong>{requestedCount}</strong>
                <span>
                  {session.preview.summary.distinct_card_names} name
                  {session.preview.summary.distinct_card_names === 1 ? "" : "s"} across{" "}
                  {session.preview.summary.distinct_printings} printing
                  {session.preview.summary.distinct_printings === 1 ? "" : "s"}.
                </span>
              </div>
              <div className="search-import-preview-card">
                <span className="search-import-preview-label">Ready now</span>
                <strong>{rowsMatched}</strong>
                <span>
                  {unresolvedCount} unresolved card
                  {unresolvedCount === 1 ? "" : "s"} still need
                  {unresolvedCount === 1 ? "s" : ""} attention.
                </span>
              </div>
            </div>
          </div>

          {resolutionProgress.blockedCount > 0 ? (
            <p className="field-hint field-hint-error">
              Some entries still do not have selectable matches. Update the source list or wait
              for backend support before continuing.
            </p>
          ) : resolutionProgress.selectedCount < resolutionProgress.requiredCount ? (
            <p className="field-hint field-hint-info">
              Choose matches for all unresolved entries to continue the import.
            </p>
          ) : (
            <p className="field-hint field-hint-success">
              All required matches are selected. Continue to commit the import.
            </p>
          )}

          <div className="search-import-resolution-list">
            {resolutionProgress.issues.map((issue) => (
              <fieldset className="form-section search-import-resolution-card" key={issue.key}>
                <legend className="search-import-resolution-legend">
                  <span className="search-import-resolution-heading">{issue.heading}</span>
                  <span className="search-import-resolution-source">{issue.sourceLabel}</span>
                </legend>
                <p className="search-import-resolution-requested">
                  Requested: {issue.requestedDetail}
                </p>
                <p className="field-hint field-hint-info">{issue.prompt}</p>

                {issue.options.length ? (
                  <div className="search-import-resolution-options">
                    {issue.options.map((option) => (
                      <label
                        className={
                          importResolutionSelections[issue.key] === option.key
                            ? "search-import-resolution-option search-import-resolution-option-active"
                            : "search-import-resolution-option"
                        }
                        key={option.key}
                      >
                        <input
                          checked={importResolutionSelections[issue.key] === option.key}
                          disabled={Boolean(importSubmitBusy)}
                          name={issue.key}
                          onChange={() =>
                            handleImportResolutionSelectionChange(issue.key, option.key)
                          }
                          type="radio"
                          value={option.key}
                        />
                        <span className="search-import-resolution-option-copy">
                          <strong>{option.name}</strong>
                          <span>{option.detail}</span>
                          <span>{option.setName}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                ) : issue.blockedMessage ? (
                  <p className="field-hint field-hint-error">{issue.blockedMessage}</p>
                ) : null}
              </fieldset>
            ))}
          </div>
        </div>
      </>
    );
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
            disabled={!hasExistingImportTargets || Boolean(importSubmitBusy)}
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
          hasExistingImportTargets ? (
            <div className="search-import-target-list">
              {existingImportTargetInventories.map((inventory) => (
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
            <p className="field-hint field-hint-info">
              No writable collections are available yet. Create a new collection to continue.
            </p>
          )
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
    <>
      {props.importActionHostEnabled && props.importActionHost
        ? createPortal(
            renderImportAction({ placement: "hero" }),
            props.importActionHost,
          )
        : null}
      <section
        ref={searchPanelRef}
        className={
          showSearchResults
            ? `panel panel-featured search-panel search-panel-results-open ${
                showSearchMatches
                  ? "search-panel-results-browse"
                  : "search-panel-results-focus"
              }`
            : "panel panel-featured search-panel"
        }
        style={searchPanelOpenStyle}
      >
        <div className="panel-heading search-panel-heading">
          <div className="search-panel-heading-copy">
            <p className="section-kicker search-panel-kicker">Card Search</p>
            <h2 className="sr-only">Card Search</h2>
          </div>
          {!props.importActionHostEnabled ? renderImportAction({ placement: "inline" }) : null}
        </div>

        <form className="search-form" onSubmit={props.actions.onSearchSubmit}>
          <label className="field search-field" ref={searchFieldRef}>
            <span className="sr-only">Quick Add and Card Search</span>
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
                ref={searchInputRef}
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
        ) : selectedInventoryAddAvailability === "read_only" ? (
          <p className="panel-hint">
            {props.state.selectedInventoryRow.display_name} is read-only. Switch to a writable
            collection to add cards, or choose another destination when importing.
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
          <div className="search-workspace-header" ref={searchWorkspaceHeaderRef}>
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
            </div>
          </div>

          <div
            className={
              showSearchMatches
                ? "search-workspace-grid"
                : "search-workspace-grid search-workspace-grid-focus"
            }
            ref={searchWorkspaceGridRef}
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
                  <div>
                    <strong>Matching cards</strong>
                    <span>Select a card to review printings.</span>
                  </div>
                  <span className="search-workspace-results-count">
                    Showing {props.state.search.groups.length} of {searchResultCount}
                  </span>
                </div>

                <div className="search-workspace-result-list" ref={searchResultListRef}>
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
                addAvailability={selectedInventoryAddAvailability}
                defaultLocation={props.state.selectedInventoryRow?.default_location || null}
                defaultTags={props.state.selectedInventoryRow?.default_tags || null}
                group={activeSearchGroup}
                onAdd={props.actions.onAdd}
                onClose={props.actions.onSearchResultsDismiss}
                onLoadPrintings={props.actions.onLoadPrintings}
                onNotice={props.actions.onNotice}
                quickAddSectionRef={searchQuickAddSectionRef}
              />
            </div>
          </div>
          {searchWorkspaceOverlay.reserveHeight > 0 ? (
            <div
              aria-hidden="true"
              className="search-workspace-reserve"
              data-search-workspace-reserve="true"
              style={{ height: `${searchWorkspaceOverlay.reserveHeight}px` }}
            />
          ) : null}
          </div>
        ) : null}

        <ModalDialog
          isOpen={activeImportDialog === "url"}
          kicker="Import Cards"
          onClose={closeImportDialog}
          size={urlImportNeedsResolution ? "wide" : "default"}
          subtitle={getImportDialogStepSubtitle("url", urlImportNeedsResolution ? "needs_resolution" : null)}
          title={getImportDialogStepTitle("url")}
        >
        <form className="search-import-form" onSubmit={handleImportUrlSubmit}>
          {urlImportNeedsResolution && activeImportSession ? (
            renderImportResolutionStep(activeImportSession)
          ) : (
            <>
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
            </>
          )}

          {importFormError ? <p className="field-hint field-hint-error">{importFormError}</p> : null}

          <div className="search-import-actions">
            <button
              className="primary-button"
              disabled={Boolean(importSubmitBusy) || (urlImportNeedsResolution && !importResolutionCanContinue)}
              type="submit"
            >
              {importSubmitBusy === "url"
                ? "Importing..."
                : urlImportNeedsResolution
                  ? "Continue import"
                  : "Import cards"}
            </button>
            {urlImportNeedsResolution ? (
              <button
                className="secondary-button"
                disabled={Boolean(importSubmitBusy)}
                onClick={handleImportBackToEdit}
                type="button"
              >
                Back to edit
              </button>
            ) : null}
            <button
              className="secondary-button"
              disabled={Boolean(importSubmitBusy)}
              onClick={() => closeImportDialog()}
              type="button"
            >
              {urlImportNeedsResolution ? "Close" : "Cancel"}
            </button>
          </div>
        </form>
        </ModalDialog>

        <ModalDialog
          isOpen={activeImportDialog === "text"}
          kicker="Import Cards"
          onClose={closeImportDialog}
          size={textImportNeedsResolution ? "wide" : "default"}
          subtitle={getImportDialogStepSubtitle("text", textImportNeedsResolution ? "needs_resolution" : null)}
          title={getImportDialogStepTitle("text")}
        >
        <form className="search-import-form" onSubmit={handleImportTextSubmit}>
          {textImportNeedsResolution && activeImportSession ? (
            renderImportResolutionStep(activeImportSession)
          ) : (
            <>
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
            </>
          )}

          {importFormError ? <p className="field-hint field-hint-error">{importFormError}</p> : null}

          <div className="search-import-actions">
            <button
              className="primary-button"
              disabled={Boolean(importSubmitBusy) || (textImportNeedsResolution && !importResolutionCanContinue)}
              type="submit"
            >
              {importSubmitBusy === "text"
                ? "Importing..."
                : textImportNeedsResolution
                  ? "Continue import"
                  : "Import cards"}
            </button>
            {textImportNeedsResolution ? (
              <button
                className="secondary-button"
                disabled={Boolean(importSubmitBusy)}
                onClick={handleImportBackToEdit}
                type="button"
              >
                Back to edit
              </button>
            ) : null}
            <button
              className="secondary-button"
              disabled={Boolean(importSubmitBusy)}
              onClick={() => closeImportDialog()}
              type="button"
            >
              {textImportNeedsResolution ? "Close" : "Cancel"}
            </button>
          </div>
        </form>
        </ModalDialog>

        <ModalDialog
          isOpen={activeImportDialog === "csv"}
          kicker="Import Cards"
          onClose={closeImportDialog}
          size={csvImportNeedsResolution ? "wide" : "default"}
          subtitle={getImportDialogStepSubtitle("csv", csvImportNeedsResolution ? "needs_resolution" : null)}
          title={getImportDialogStepTitle("csv")}
        >
        <form className="search-import-form" onSubmit={handleImportCsvSubmit}>
          {csvImportNeedsResolution && activeImportSession ? (
            renderImportResolutionStep(activeImportSession)
          ) : (
            <>
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
            </>
          )}

          {importFormError ? <p className="field-hint field-hint-error">{importFormError}</p> : null}

          <div className="search-import-actions">
            <button
              className="primary-button"
              disabled={Boolean(importSubmitBusy) || (csvImportNeedsResolution && !importResolutionCanContinue)}
              type="submit"
            >
              {importSubmitBusy === "csv"
                ? "Importing..."
                : csvImportNeedsResolution
                  ? "Continue import"
                  : "Import cards"}
            </button>
            {csvImportNeedsResolution ? (
              <button
                className="secondary-button"
                disabled={Boolean(importSubmitBusy)}
                onClick={handleImportBackToEdit}
                type="button"
              >
                Back to edit
              </button>
            ) : null}
            <button
              className="secondary-button"
              disabled={Boolean(importSubmitBusy)}
              onClick={() => closeImportDialog()}
              type="button"
            >
              {csvImportNeedsResolution ? "Close" : "Cancel"}
            </button>
          </div>
        </form>
        </ModalDialog>
      </section>
    </>
  );
}
