import type {
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

export type InventoryOverviewState = {
  selectedInventoryRow: InventorySummary | null;
  items: OwnedInventoryRow[];
  auditEvents: InventoryAuditEvent[];
  viewStatus: AsyncStatus;
  viewError: string | null;
};
