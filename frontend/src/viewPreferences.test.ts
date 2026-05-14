import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FRONTEND_VIEW_PREFERENCES_STORAGE_KEY,
  loadCollectionViewPreference,
  saveCollectionViewPreference,
} from "./viewPreferences";

describe("view preferences", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  it("defaults collection view to browse when no preference is stored", () => {
    expect(loadCollectionViewPreference()).toBe("browse");
  });

  it("persists the selected collection view locally", () => {
    saveCollectionViewPreference("table");

    expect(loadCollectionViewPreference()).toBe("table");
    expect(
      JSON.parse(
        window.localStorage.getItem(FRONTEND_VIEW_PREFERENCES_STORAGE_KEY) || "{}",
      ),
    ).toEqual({ collectionView: "table" });
  });

  it("ignores invalid stored collection view preferences", () => {
    window.localStorage.setItem(
      FRONTEND_VIEW_PREFERENCES_STORAGE_KEY,
      JSON.stringify({ collectionView: "grid" }),
    );

    expect(loadCollectionViewPreference()).toBe("browse");
  });

  it("does not throw when local storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage blocked");
    });

    expect(loadCollectionViewPreference()).toBe("browse");
    expect(() => saveCollectionViewPreference("table")).not.toThrow();
  });
});
