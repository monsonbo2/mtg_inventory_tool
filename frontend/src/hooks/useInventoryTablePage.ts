import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { listInventoryItemsPage } from "../api";
import type {
  OwnedInventoryItemsPageParams,
  OwnedInventoryItemsPageResponse,
  OwnedInventoryRow,
} from "../types";
import type {
  InventoryTableFilters,
  InventoryTableSortState,
} from "../tableViewHelpers";
import { serializeInventoryTableFilters } from "../tableViewHelpers";
import { toUserMessage } from "../uiHelpers";
import type { AsyncStatus } from "../uiTypes";

function getPageCount(totalItems: number, pageSize: number) {
  return Math.max(1, Math.ceil(totalItems / pageSize));
}

export function buildInventoryTablePageParams(options: {
  filters: InventoryTableFilters;
  page: number;
  sort: InventoryTableSortState;
  visibleLimit: number;
}): OwnedInventoryItemsPageParams {
  const { params: filterParams } = serializeInventoryTableFilters(options.filters);
  const params: OwnedInventoryItemsPageParams = {
    ...filterParams,
    limit: options.visibleLimit,
    offset: (Math.max(options.page, 1) - 1) * options.visibleLimit,
  };

  if (options.sort) {
    params.sort_key = options.sort.key;
    params.sort_direction = options.sort.direction;
  }

  return params;
}

export function useInventoryTablePage(options: {
  enabled: boolean;
  filters: InventoryTableFilters;
  inventorySlug: string | null;
  onPageOutOfRange?: (nextPage: number) => void;
  page: number;
  sort: InventoryTableSortState;
  visibleLimit: number;
}) {
  const [items, setItems] = useState<OwnedInventoryRow[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [limit, setLimit] = useState(options.visibleLimit);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [status, setStatus] = useState<AsyncStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const requestIdRef = useRef(0);
  const onPageOutOfRangeRef = useRef(options.onPageOutOfRange);

  useEffect(() => {
    onPageOutOfRangeRef.current = options.onPageOutOfRange;
  }, [options.onPageOutOfRange]);

  const params = useMemo(
    () =>
      buildInventoryTablePageParams({
        filters: options.filters,
        page: options.page,
        sort: options.sort,
        visibleLimit: options.visibleLimit,
      }),
    [options.filters, options.page, options.sort, options.visibleLimit],
  );

  useEffect(() => {
    if (!options.enabled || !options.inventorySlug) {
      requestIdRef.current += 1;
      setItems([]);
      setTotalCount(0);
      setLimit(options.visibleLimit);
      setOffset(0);
      setHasMore(false);
      setStatus("idle");
      setError(null);
      return;
    }

    const requestId = ++requestIdRef.current;
    setStatus("loading");
    setError(null);

    async function loadTablePage() {
      try {
        const response: OwnedInventoryItemsPageResponse = await listInventoryItemsPage(
          options.inventorySlug!,
          params,
        );

        if (requestId !== requestIdRef.current) {
          return;
        }

        if (
          response.items.length === 0 &&
          response.offset > 0 &&
          response.total_count > 0
        ) {
          const lastPage = getPageCount(response.total_count, response.limit);
          if (lastPage < options.page) {
            onPageOutOfRangeRef.current?.(lastPage);
            return;
          }
        }

        setItems(response.items);
        setTotalCount(response.total_count);
        setLimit(response.limit);
        setOffset(response.offset);
        setHasMore(response.has_more);
        setError(null);
        setStatus("ready");
      } catch (loadError) {
        if (requestId !== requestIdRef.current) {
          return;
        }
        setError(toUserMessage(loadError, "Could not load table rows."));
        setStatus("error");
      }
    }

    void loadTablePage();
  }, [
    options.enabled,
    options.inventorySlug,
    options.page,
    options.visibleLimit,
    params,
    reloadToken,
  ]);

  const refreshTablePage = useCallback(() => {
    setReloadToken((current) => current + 1);
  }, []);

  return {
    error,
    hasMore,
    items,
    limit,
    offset,
    pageCount: getPageCount(totalCount, options.visibleLimit),
    refreshTablePage,
    status: options.enabled && status === "idle" ? "loading" : status,
    totalCount,
  };
}
