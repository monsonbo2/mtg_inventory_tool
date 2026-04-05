import { useEffect, useRef, useState } from "react";

import {
  ApiClientError,
  listInventories,
  listInventoryAudit,
  listInventoryItems,
} from "../api";
import type {
  InventoryAuditEvent,
  InventorySummary,
  OwnedInventoryRow,
} from "../types";
import { resolveSelectedInventorySlug, toUserMessage } from "../uiHelpers";
import type { AsyncStatus, ViewRefreshOutcome } from "../uiTypes";

type LoadInventoryOverviewOptions = {
  reloadInventories?: boolean;
  showLoading?: boolean;
};

export function useInventoryOverview() {
  const [inventories, setInventories] = useState<InventorySummary[]>([]);
  const [selectedInventory, setSelectedInventory] = useState<string | null>(null);
  const [items, setItems] = useState<OwnedInventoryRow[]>([]);
  const [auditEvents, setAuditEvents] = useState<InventoryAuditEvent[]>([]);
  const [inventoryStatus, setInventoryStatus] = useState<AsyncStatus>("loading");
  const [viewStatus, setViewStatus] = useState<AsyncStatus>("idle");
  const [inventoryError, setInventoryError] = useState<string | null>(null);
  const [inventoryErrorStatus, setInventoryErrorStatus] = useState<number | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
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
        setInventoryErrorStatus(null);
        setSelectedInventory((current) =>
          resolveSelectedInventorySlug(nextInventories, current),
        );
        setInventoryStatus("ready");
      } catch (error) {
        if (cancelled) {
          return;
        }
        setInventoryError(toUserMessage(error, "Could not load collections."));
        setInventoryErrorStatus(
          error instanceof ApiClientError ? error.status : null,
        );
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

  async function reloadInventorySummaries(preferredSlug: string | null = null) {
    try {
      const nextInventories = await listInventories();
      setInventories(nextInventories);
      setInventoryError(null);
      setInventoryErrorStatus(null);
      setInventoryStatus("ready");

      const nextSelectedInventory = resolveSelectedInventorySlug(
        nextInventories,
        preferredSlug ?? selectedInventoryRef.current,
      );

      if (nextSelectedInventory !== selectedInventoryRef.current) {
        selectedInventoryRef.current = nextSelectedInventory;
        setSelectedInventory(nextSelectedInventory);
      }

      return true;
    } catch (error) {
      setInventoryError(toUserMessage(error, "Could not refresh collection totals."));
      setInventoryErrorStatus(error instanceof ApiClientError ? error.status : null);
      setInventoryStatus("error");
      return false;
    }
  }

  async function loadInventoryOverview(
    inventorySlug: string,
    options: LoadInventoryOverviewOptions = {},
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

  function describeInventory(inventorySlug: string) {
    return (
      inventories.find((inventory) => inventory.slug === inventorySlug)?.display_name ||
      inventorySlug
    );
  }

  const selectedInventoryRow =
    inventories.find((inventory) => inventory.slug === selectedInventory) ?? null;

  return {
    auditEvents,
    describeInventory,
    inventories,
    inventoryError,
    inventoryErrorStatus,
    inventoryStatus,
    items,
    loadInventoryOverview,
    reloadInventorySummaries,
    selectedInventory,
    selectedInventoryRow,
    setSelectedInventory,
    viewError,
    viewStatus,
  };
}
