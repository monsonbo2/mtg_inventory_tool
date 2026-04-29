import type {
  CsvImportResolutionRequest,
  CsvImportResponse,
  DeckUrlImportResolutionRequest,
  DeckUrlImportResponse,
  DecklistImportResolutionRequest,
  DecklistImportResponse,
  InventoryAuditEvent,
  InventoryCreateResponse,
  InventorySummary,
  OwnedInventoryRow,
} from "./types";

export type AsyncStatus = "idle" | "loading" | "ready" | "error";
export type AppShellState =
  | "loading"
  | "ready"
  | "bootstrap_available"
  | "access_needed"
  | "error";
export type ViewRefreshOutcome = "applied" | "skipped";
export type MutationOutcome = "applied" | "applied_view_stale" | "failed";
export type NoticeTone = "info" | "success" | "error";
export type SearchAddAvailability = "unselected" | "read_only" | "writable";
export type InventoryImportMode = "csv" | "decklist" | "deck_url";
export type InventoryImportStep = "ready_to_commit" | "needs_resolution";
export type ItemMutationAction =
  | "quantity"
  | "finish"
  | "location"
  | "notes"
  | "tags"
  | "delete";

export type ItemMutationState = {
  itemId: number;
  action: ItemMutationAction;
};

export type NoticeState = {
  message: string;
  tone: NoticeTone;
};

export type InventoryCreateResult =
  | {
      ok: true;
      inventory: InventoryCreateResponse;
    }
  | {
      ok: false;
      reason: "conflict" | "error";
    };

export type SearchResultNoticeHandler = (message: string, tone?: NoticeTone) => void;
export type OwnedRowNoticeHandler = (message: string, tone?: NoticeTone) => void;

type InventoryImportSessionBase = {
  inventorySlug: string;
  inventoryLabel: string | null;
  step: InventoryImportStep;
};

export type CsvImportSession = InventoryImportSessionBase & {
  mode: "csv";
  source: {
    file: Blob;
  };
  preview: CsvImportResponse;
};

export type DecklistImportSession = InventoryImportSessionBase & {
  mode: "decklist";
  source: {
    deckText: string;
  };
  preview: DecklistImportResponse;
};

export type DeckUrlImportSession = InventoryImportSessionBase & {
  mode: "deck_url";
  source: {
    sourceUrl: string;
  };
  preview: DeckUrlImportResponse;
};

export type InventoryImportSession =
  | CsvImportSession
  | DecklistImportSession
  | DeckUrlImportSession;

export type InventoryImportPreviewResult =
  | {
      ok: true;
      session: InventoryImportSession;
    }
  | {
      ok: false;
      reason: "missing_inventory" | "error";
    };

export type InventoryImportCommitResult =
  | {
      ok: true;
      refreshOutcome: MutationOutcome;
      session: InventoryImportSession;
    }
  | {
      ok: false;
      reason: "error" | "still_needs_resolution";
      session?: InventoryImportSession;
    };

export type InventoryImportResolutionSelections =
  | {
      mode: "csv";
      resolutions: CsvImportResolutionRequest[];
    }
  | {
      mode: "decklist";
      resolutions: DecklistImportResolutionRequest[];
    }
  | {
      mode: "deck_url";
      resolutions: DeckUrlImportResolutionRequest[];
    };

export type InventoryOverviewState = {
  selectedInventoryRow: InventorySummary | null;
  items: OwnedInventoryRow[];
  auditEvents: InventoryAuditEvent[];
  viewStatus: AsyncStatus;
  viewError: string | null;
};
