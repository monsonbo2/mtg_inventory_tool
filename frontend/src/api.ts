import type {
  AddInventoryItemRequest,
  ApiErrorEnvelope,
  CatalogSearchRow,
  InventoryAuditEvent,
  InventoryItemMutationResponse,
  InventorySummary,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
  SearchCardsParams,
} from "./types";

const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL || "/api").trim();
const apiBaseUrl = configuredBaseUrl.endsWith("/")
  ? configuredBaseUrl.slice(0, -1)
  : configuredBaseUrl;

type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | Array<string | number | boolean>;

export class ApiClientError extends Error {
  code: string;
  status: number;

  constructor(message: string, options: { code: string; status: number }) {
    super(message);
    this.name = "ApiClientError";
    this.code = options.code;
    this.status = options.status;
  }
}

function buildUrl(path: string, query?: Record<string, QueryValue>) {
  const url = new URL(`${apiBaseUrl}${path}`, window.location.origin);

  if (!query) {
    return url;
  }

  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        url.searchParams.append(key, String(item));
      }
      continue;
    }
    url.searchParams.set(key, String(value));
  }

  return url;
}

async function readJson(response: Response) {
  const text = await response.text();
  if (!text) {
    return null;
  }
  return JSON.parse(text) as unknown;
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  query?: Record<string, QueryValue>,
) {
  const response = await fetch(buildUrl(path, query), {
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
    ...options,
  });

  const payload = await readJson(response);

  if (!response.ok) {
    const errorEnvelope = payload as ApiErrorEnvelope | null;
    throw new ApiClientError(
      errorEnvelope?.error?.message || "The API request failed.",
      {
        code: errorEnvelope?.error?.code || "http_error",
        status: response.status,
      },
    );
  }

  return payload as T;
}

export async function listInventories() {
  return request<InventorySummary[]>("/inventories");
}

export async function searchCards(params: SearchCardsParams) {
  return request<CatalogSearchRow[]>("/cards/search", {}, params);
}

export async function listInventoryItems(inventorySlug: string) {
  return request<OwnedInventoryRow[]>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items`,
  );
}

export async function listInventoryAudit(inventorySlug: string) {
  return request<InventoryAuditEvent[]>(
    `/inventories/${encodeURIComponent(inventorySlug)}/audit`,
    {},
    { limit: 12 },
  );
}

export async function addInventoryItem(
  inventorySlug: string,
  payload: AddInventoryItemRequest,
) {
  return request<InventoryItemMutationResponse>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function patchInventoryItem(
  inventorySlug: string,
  itemId: number,
  payload: PatchInventoryItemRequest,
) {
  return request<InventoryItemMutationResponse>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items/${itemId}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteInventoryItem(
  inventorySlug: string,
  itemId: number,
) {
  return request<InventoryItemMutationResponse>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items/${itemId}`,
    {
      method: "DELETE",
    },
  );
}
