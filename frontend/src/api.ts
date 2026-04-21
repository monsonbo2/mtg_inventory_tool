import type {
  AddInventoryItemRequest,
  ApiErrorEnvelope,
  AccessSummaryResponse,
  BulkInventoryItemMutationRequest,
  BulkInventoryItemMutationResponse,
  CardPrintingSummaryParams,
  CatalogNameSearchResult,
  CatalogPrintingLookupRow,
  CatalogPrintingSummaryResponse,
  CatalogSearchRow,
  CsvImportRequest,
  CsvImportResponse,
  DeckUrlImportRequest,
  DeckUrlImportResponse,
  DecklistImportRequest,
  DecklistImportResponse,
  DefaultInventoryBootstrapResponse,
  InventoryAuditEvent,
  InventoryCreateRequest,
  InventoryCreateResponse,
  InventoryDuplicateRequest,
  InventoryDuplicateResponse,
  InventoryExportCsvParams,
  InventoryItemPatchResponse,
  InventoryItemMutationResponse,
  InventorySummary,
  SetInventoryItemPrintingRequest,
  SetPrintingResponse,
  InventoryTransferRequest,
  InventoryTransferResponse,
  ListCardPrintingsParams,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
  SearchCardNamesParams,
  SearchCardsParams,
} from "./types";

const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL || "/api").trim();
const apiBaseUrl = configuredBaseUrl.endsWith("/")
  ? configuredBaseUrl.slice(0, -1)
  : configuredBaseUrl;

const JSON_ACCEPT_HEADER = "application/json";

type QueryValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | Array<string | number | boolean>;

type RequestQuery = Record<string, QueryValue>;

type BaseRequestOptions = Omit<RequestInit, "body" | "headers"> & {
  accept?: string;
  headers?: HeadersInit;
  query?: RequestQuery;
};

type JsonRequestOptions = BaseRequestOptions & {
  body?: unknown;
};

type FormDataRequestOptions = BaseRequestOptions & {
  formData: FormData;
};

export type ApiTextResponse = {
  body: string;
  contentType: string | null;
  filename: string | null;
};

type ApiErrorDetails = Record<string, unknown> | null;

export class ApiClientError extends Error {
  code: string;
  details: ApiErrorDetails;
  status: number;

  constructor(
    message: string,
    options: {
      code: string;
      details?: ApiErrorDetails;
      status: number;
    },
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = options.code;
    this.details = options.details ?? null;
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

function buildRequestInit(
  options: BaseRequestOptions,
  body?: BodyInit | null,
  contentType?: string,
) {
  const { accept = JSON_ACCEPT_HEADER, headers, query: _query, ...requestInit } = options;
  const nextHeaders = new Headers(headers);

  if (!nextHeaders.has("Accept")) {
    nextHeaders.set("Accept", accept);
  }

  if (contentType && !nextHeaders.has("Content-Type")) {
    nextHeaders.set("Content-Type", contentType);
  }

  return {
    ...requestInit,
    body,
    headers: nextHeaders,
  };
}

async function readResponseText(response: Response) {
  return response.text();
}

function isJsonContentType(contentType: string | null) {
  return contentType?.toLowerCase().includes("application/json") ?? false;
}

function tryParseJson(text: string) {
  if (!text.trim()) {
    return null;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

async function readJsonResponse<T>(response: Response) {
  const text = await readResponseText(response);
  if (!text) {
    return null as T;
  }
  return JSON.parse(text) as T;
}

function getFilenameFromContentDisposition(contentDisposition: string | null) {
  if (!contentDisposition) {
    return null;
  }

  const utf8FilenameMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8FilenameMatch) {
    try {
      return decodeURIComponent(utf8FilenameMatch[1]);
    } catch {
      return utf8FilenameMatch[1];
    }
  }

  const quotedFilenameMatch = contentDisposition.match(/filename="([^"]+)"/i);
  if (quotedFilenameMatch) {
    return quotedFilenameMatch[1];
  }

  const bareFilenameMatch = contentDisposition.match(/filename=([^;]+)/i);
  if (bareFilenameMatch) {
    return bareFilenameMatch[1].trim();
  }

  return null;
}

async function readTextResponse(response: Response): Promise<ApiTextResponse> {
  return {
    body: await readResponseText(response),
    contentType: response.headers.get("Content-Type"),
    filename: getFilenameFromContentDisposition(
      response.headers.get("Content-Disposition"),
    ),
  };
}

async function throwApiClientError(response: Response): Promise<never> {
  const contentType = response.headers.get("Content-Type");
  const text = await readResponseText(response);
  const parsedPayload =
    isJsonContentType(contentType) || text.trim().startsWith("{")
      ? tryParseJson(text)
      : null;
  const errorEnvelope = parsedPayload as ApiErrorEnvelope | null;

  throw new ApiClientError(
    errorEnvelope?.error?.message || text.trim() || "The API request failed.",
    {
      code: errorEnvelope?.error?.code || "http_error",
      details: errorEnvelope?.error?.details ?? null,
      status: response.status,
    },
  );
}

async function requestWithParser<T>(
  path: string,
  options: BaseRequestOptions,
  parser: (response: Response) => Promise<T>,
  body?: BodyInit | null,
  contentType?: string,
) {
  const response = await fetch(
    buildUrl(path, options.query),
    buildRequestInit(options, body, contentType),
  );

  if (!response.ok) {
    await throwApiClientError(response);
  }

  return parser(response);
}

export async function requestJson<T>(path: string, options: JsonRequestOptions = {}) {
  const jsonBody = options.body === undefined ? undefined : JSON.stringify(options.body);
  return requestWithParser<T>(
    path,
    {
      ...options,
      accept: options.accept || JSON_ACCEPT_HEADER,
    },
    readJsonResponse<T>,
    jsonBody,
    jsonBody === undefined ? undefined : "application/json",
  );
}

export async function requestFormData<T>(
  path: string,
  options: FormDataRequestOptions,
) {
  return requestWithParser<T>(
    path,
    {
      ...options,
      accept: options.accept || JSON_ACCEPT_HEADER,
    },
    readJsonResponse<T>,
    options.formData,
  );
}

export async function requestText(path: string, options: BaseRequestOptions = {}) {
  return requestWithParser<ApiTextResponse>(
    path,
    {
      ...options,
      accept: options.accept || "text/plain, text/csv;q=0.9, */*;q=0.1",
    },
    readTextResponse,
  );
}

function appendOptionalFormDataValue(
  formData: FormData,
  key: string,
  value: string | boolean | null | undefined,
) {
  if (value === undefined || value === null) {
    return;
  }

  formData.set(key, String(value));
}

function buildCsvImportFormData(payload: CsvImportRequest) {
  const formData = new FormData();
  const filename =
    typeof File !== "undefined" && payload.file instanceof File
      ? payload.file.name
      : "import.csv";

  formData.set("file", payload.file, filename);
  appendOptionalFormDataValue(
    formData,
    "default_inventory",
    payload.default_inventory,
  );
  appendOptionalFormDataValue(formData, "dry_run", payload.dry_run);

  if (payload.resolutions !== undefined) {
    formData.set("resolutions_json", JSON.stringify(payload.resolutions));
  }

  return formData;
}

export async function listInventories() {
  return requestJson<InventorySummary[]>("/inventories");
}

export async function getAccessSummary() {
  return requestJson<AccessSummaryResponse>("/me/access-summary");
}

export async function createInventory(payload: InventoryCreateRequest) {
  return requestJson<InventoryCreateResponse>("/inventories", {
    method: "POST",
    body: payload,
  });
}

export async function bootstrapDefaultInventory() {
  return requestJson<DefaultInventoryBootstrapResponse>("/me/bootstrap", {
    method: "POST",
  });
}

export async function searchCards(params: SearchCardsParams) {
  return requestJson<CatalogSearchRow[]>("/cards/search", {
    query: {
      query: params.query,
      set_code: params.set_code,
      rarity: params.rarity,
      finish: params.finish,
      lang: params.lang,
      scope: params.scope,
      exact: params.exact,
      limit: params.limit,
    },
  });
}

export async function searchCardNames(params: SearchCardNamesParams) {
  return requestJson<CatalogNameSearchResult>("/cards/search/names", {
    query: {
      query: params.query,
      scope: params.scope,
      exact: params.exact,
      limit: params.limit,
    },
  });
}

export async function listCardPrintings(
  oracleId: string,
  params: ListCardPrintingsParams = {},
) {
  return requestJson<CatalogPrintingLookupRow[]>(
    `/cards/oracle/${encodeURIComponent(oracleId)}/printings`,
    {
      query: { lang: params.lang, scope: params.scope },
    },
  );
}

export async function getCardPrintingSummary(
  oracleId: string,
  params: CardPrintingSummaryParams = {},
) {
  return requestJson<CatalogPrintingSummaryResponse>(
    `/cards/oracle/${encodeURIComponent(oracleId)}/printings/summary`,
    {
      query: { scope: params.scope },
    },
  );
}

export async function listInventoryItems(inventorySlug: string) {
  return requestJson<OwnedInventoryRow[]>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items`,
  );
}

export async function listInventoryAudit(inventorySlug: string) {
  return requestJson<InventoryAuditEvent[]>(
    `/inventories/${encodeURIComponent(inventorySlug)}/audit`,
    {
      query: { limit: 12 },
    },
  );
}

export async function exportInventoryCsv(
  inventorySlug: string,
  params: InventoryExportCsvParams = {},
) {
  return requestText(`/inventories/${encodeURIComponent(inventorySlug)}/export.csv`, {
    query: {
      provider: params.provider,
      profile: params.profile,
      limit: params.limit,
      query: params.query,
      set_code: params.set_code,
      rarity: params.rarity,
      finish: params.finish,
      condition_code: params.condition_code,
      language_code: params.language_code,
      location: params.location,
      tags: params.tags,
    },
  });
}

export async function bulkMutateInventoryItems(
  inventorySlug: string,
  payload: BulkInventoryItemMutationRequest,
) {
  return requestJson<BulkInventoryItemMutationResponse>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items/bulk`,
    {
      method: "POST",
      body: payload,
    },
  );
}

export async function addInventoryItem(
  inventorySlug: string,
  payload: AddInventoryItemRequest,
) {
  return requestJson<InventoryItemMutationResponse>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items`,
    {
      method: "POST",
      body: payload,
    },
  );
}

export async function patchInventoryItem(
  inventorySlug: string,
  itemId: number,
  payload: PatchInventoryItemRequest,
) {
  return requestJson<InventoryItemPatchResponse>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items/${itemId}`,
    {
      method: "PATCH",
      body: payload,
    },
  );
}

export async function setInventoryItemPrinting(
  inventorySlug: string,
  itemId: number,
  payload: SetInventoryItemPrintingRequest,
) {
  return requestJson<SetPrintingResponse>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items/${itemId}/printing`,
    {
      method: "PATCH",
      body: payload,
    },
  );
}

export async function deleteInventoryItem(
  inventorySlug: string,
  itemId: number,
) {
  return requestJson<InventoryItemMutationResponse>(
    `/inventories/${encodeURIComponent(inventorySlug)}/items/${itemId}`,
    {
      method: "DELETE",
    },
  );
}

export async function importCsv(payload: CsvImportRequest) {
  return requestFormData<CsvImportResponse>("/imports/csv", {
    formData: buildCsvImportFormData(payload),
    method: "POST",
  });
}

export async function importDecklist(payload: DecklistImportRequest) {
  return requestJson<DecklistImportResponse>("/imports/decklist", {
    method: "POST",
    body: payload,
  });
}

export async function importDeckUrl(payload: DeckUrlImportRequest) {
  return requestJson<DeckUrlImportResponse>("/imports/deck-url", {
    method: "POST",
    body: payload,
  });
}

export async function duplicateInventory(
  sourceInventorySlug: string,
  payload: InventoryDuplicateRequest,
) {
  return requestJson<InventoryDuplicateResponse>(
    `/inventories/${encodeURIComponent(sourceInventorySlug)}/duplicate`,
    {
      method: "POST",
      body: payload,
    },
  );
}

export async function transferInventoryItems(
  sourceInventorySlug: string,
  payload: InventoryTransferRequest,
) {
  return requestJson<InventoryTransferResponse>(
    `/inventories/${encodeURIComponent(sourceInventorySlug)}/transfer`,
    {
      method: "POST",
      body: payload,
    },
  );
}
