import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadApiTextResponse } from "./downloadHelpers";

describe("download helpers", () => {
  const originalCreateObjectUrl = URL.createObjectURL;
  const originalRevokeObjectUrl = URL.revokeObjectURL;

  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: originalCreateObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectUrl,
    });
  });

  it("downloads API text responses with response filename metadata", () => {
    const createObjectUrl = vi.fn((_blob: Blob) => "blob:inventory-export");
    const revokeObjectUrl = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      () => undefined,
    );

    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectUrl,
    });

    downloadApiTextResponse(
      {
        body: "name,quantity\nLightning Bolt,4\n",
        contentType: "text/csv; charset=utf-8",
        filename: "personal.csv",
      },
      "fallback.csv",
    );

    expect(createObjectUrl).toHaveBeenCalledTimes(1);
    const blob = createObjectUrl.mock.calls[0][0] as Blob;
    expect(blob.type).toBe("text/csv; charset=utf-8");
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:inventory-export");
  });

  it("falls back to a caller-provided filename", () => {
    const createObjectUrl = vi.fn((_blob: Blob) => "blob:fallback-export");
    const revokeObjectUrl = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      function clickAnchor(this: HTMLAnchorElement) {
        expect(this.download).toBe("fallback.csv");
      },
    );

    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectUrl,
    });

    downloadApiTextResponse(
      {
        body: "name,quantity\nCounterspell,2\n",
        contentType: null,
        filename: "  ",
      },
      "fallback.csv",
    );

    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:fallback-export");
  });
});
