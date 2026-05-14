export type CollectionViewPreference = "browse" | "table";

export const FRONTEND_VIEW_PREFERENCES_STORAGE_KEY =
  "mtg-inventory.view-preferences.v1";

type FrontendViewPreferences = {
  collectionView?: CollectionViewPreference;
};

function getLocalStorage() {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isCollectionViewPreference(value: unknown): value is CollectionViewPreference {
  return value === "browse" || value === "table";
}

function readViewPreferences(): FrontendViewPreferences {
  const storage = getLocalStorage();
  if (!storage) {
    return {};
  }

  try {
    const rawValue = storage.getItem(FRONTEND_VIEW_PREFERENCES_STORAGE_KEY);
    if (!rawValue) {
      return {};
    }
    const parsed = JSON.parse(rawValue) as unknown;
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const collectionView = (parsed as { collectionView?: unknown }).collectionView;
    return isCollectionViewPreference(collectionView) ? { collectionView } : {};
  } catch {
    return {};
  }
}

export function loadCollectionViewPreference(): CollectionViewPreference {
  return readViewPreferences().collectionView ?? "browse";
}

export function saveCollectionViewPreference(nextView: CollectionViewPreference) {
  const storage = getLocalStorage();
  if (!storage) {
    return;
  }

  try {
    const currentPreferences = readViewPreferences();
    storage.setItem(
      FRONTEND_VIEW_PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        ...currentPreferences,
        collectionView: nextView,
      }),
    );
  } catch {
    // Local preferences should never block the live collection view.
  }
}
