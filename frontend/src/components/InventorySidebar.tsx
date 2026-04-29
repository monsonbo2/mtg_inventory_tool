import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import type { InventoryCreateRequest, InventorySummary } from "../types";
import {
  normalizeInventorySlugInput,
  normalizeOptionalText,
  normalizeTagInputText,
} from "../uiHelpers";
import type { AppShellState, InventoryCreateResult } from "../uiTypes";
import { ModalDialog } from "./ui/ModalDialog";
import { PanelState } from "./ui/PanelState";

function getOtherInventoryCountLabel(availableCount: number) {
  if (availableCount === 0) {
    return "No other collections available";
  }

  return availableCount === 1
    ? "1 other collection available"
    : `${availableCount} other collections available`;
}

function getInventoryStatsLabel(inventory: InventorySummary) {
  return `${inventory.item_rows} entr${inventory.item_rows === 1 ? "y" : "ies"} · ${inventory.total_cards} cards`;
}

function InventoryCardSummary(props: {
  inventory: InventorySummary;
  showDescription?: boolean;
}) {
  return (
    <>
      <strong className="inventory-focus-title">{props.inventory.display_name}</strong>
      {props.showDescription !== false ? (
        <p>{props.inventory.description || "No description provided for this collection."}</p>
      ) : null}
      <div className="inventory-selector-footer">
        <span>{getInventoryStatsLabel(props.inventory)}</span>
      </div>
    </>
  );
}

function InventorySwitcherOption(props: {
  inventory: InventorySummary;
  onSelect: (inventorySlug: string) => void;
  autoFocus?: boolean;
}) {
  return (
    <button
      className="inventory-switcher-option"
      autoFocus={props.autoFocus}
      onClick={() => props.onSelect(props.inventory.slug)}
      type="button"
    >
      <InventoryCardSummary inventory={props.inventory} showDescription={false} />
    </button>
  );
}

export function InventorySidebar(props: {
  appShellState: AppShellState;
  collectionMenuInteractionEnabled: boolean;
  collectionMenuOpen: boolean;
  createInventoryBusy: boolean;
  inventories: InventorySummary[];
  selectedInventory: string | null;
  selectedInventoryRow: InventorySummary | null;
  inventoryError: string | null;
  onCollectionMenuOpenChange: (open: boolean) => void;
  onCreateInventory: (payload: InventoryCreateRequest) => Promise<InventoryCreateResult>;
  onSelectInventory: (inventorySlug: string) => void;
}) {
  const [createFormOpen, setCreateFormOpen] = useState(false);
  const inventorySwitcherId = useId();
  const inventorySwitcherRef = useRef<HTMLDivElement | null>(null);
  const inventorySwitcherListRef = useRef<HTMLDivElement | null>(null);
  const [inventorySwitcherOverlayHeight, setInventorySwitcherOverlayHeight] = useState(0);
  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [showShortNameField, setShowShortNameField] = useState(false);
  const [description, setDescription] = useState("");
  const [defaultLocation, setDefaultLocation] = useState("");
  const [defaultTags, setDefaultTags] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const currentInventory =
    props.selectedInventoryRow ??
    props.inventories.find((inventory) => inventory.slug === props.selectedInventory) ??
    props.inventories[0] ??
    null;
  const otherInventories = currentInventory
    ? props.inventories.filter((inventory) => inventory.slug !== currentInventory.slug)
    : props.inventories;
  const changeCollectionOpen = props.collectionMenuOpen;

  useEffect(() => {
    props.onCollectionMenuOpenChange(false);
  }, [props.selectedInventory]);

  useEffect(() => {
    if (props.appShellState !== "ready") {
      setCreateFormOpen(false);
      props.onCollectionMenuOpenChange(false);
      resetCreateForm();
    }
  }, [props.appShellState]);

  useEffect(() => {
    if (!changeCollectionOpen || !props.collectionMenuInteractionEnabled) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (inventorySwitcherRef.current?.contains(target)) {
        return;
      }
      props.onCollectionMenuOpenChange(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [changeCollectionOpen, props.collectionMenuInteractionEnabled]);

  useLayoutEffect(() => {
    if (!changeCollectionOpen || !props.collectionMenuInteractionEnabled) {
      setInventorySwitcherOverlayHeight(0);
      return;
    }

    function updateInventorySwitcherOverlayHeight() {
      const switcherNode = inventorySwitcherRef.current;
      const listNode = inventorySwitcherListRef.current;
      if (!switcherNode || !listNode || window.innerWidth <= 820) {
        setInventorySwitcherOverlayHeight(0);
        return;
      }

      const computedStyle = window.getComputedStyle(switcherNode);
      const rowGap = Number.parseFloat(computedStyle.rowGap || computedStyle.gap || "0");
      setInventorySwitcherOverlayHeight(
        Math.max(0, Math.round(listNode.getBoundingClientRect().height + rowGap)),
      );
    }

    updateInventorySwitcherOverlayHeight();

    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            updateInventorySwitcherOverlayHeight();
          });

    if (resizeObserver && inventorySwitcherListRef.current) {
      resizeObserver.observe(inventorySwitcherListRef.current);
    }

    window.addEventListener("resize", updateInventorySwitcherOverlayHeight);
    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", updateInventorySwitcherOverlayHeight);
    };
  }, [changeCollectionOpen, props.collectionMenuInteractionEnabled]);

  function resetCreateForm() {
    setDisplayName("");
    setSlug("");
    setShowShortNameField(false);
    setDescription("");
    setDefaultLocation("");
    setDefaultTags("");
    setSlugTouched(false);
    setFormError(null);
  }

  function openCreateForm() {
    setCreateFormOpen(true);
    props.onCollectionMenuOpenChange(false);
    setFormError(null);
  }

  function closeCreateForm() {
    setCreateFormOpen(false);
    resetCreateForm();
  }

  function handleDisplayNameChange(value: string) {
    setDisplayName(value);
    if (!slugTouched) {
      setSlug(normalizeInventorySlugInput(value));
    }
    if (formError) {
      setFormError(null);
    }
  }

  function handleSlugChange(value: string) {
    setSlugTouched(true);
    setSlug(normalizeInventorySlugInput(value));
    if (formError) {
      setFormError(null);
    }
  }

  function handleDescriptionChange(value: string) {
    setDescription(value);
    if (formError) {
      setFormError(null);
    }
  }

  function handleDefaultLocationChange(value: string) {
    setDefaultLocation(value);
    if (formError) {
      setFormError(null);
    }
  }

  function handleDefaultTagsChange(value: string) {
    setDefaultTags(value);
    if (formError) {
      setFormError(null);
    }
  }

  async function handleCreateSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextDisplayName = displayName.trim();
    const nextSlug = normalizeInventorySlugInput(slug);
    const nextDefaultLocation = normalizeOptionalText(defaultLocation);
    const nextDefaultTags = normalizeTagInputText(defaultTags);

    if (!nextDisplayName) {
      setFormError("Enter a collection name before creating it.");
      return;
    }

    if (!nextSlug) {
      setFormError("Enter a short name using letters, numbers, or hyphens.");
      return;
    }

    const createPayload: InventoryCreateRequest = {
      display_name: nextDisplayName,
      slug: nextSlug,
      description: normalizeOptionalText(description),
    };
    if (nextDefaultLocation) {
      createPayload.default_location = nextDefaultLocation;
    }
    if (nextDefaultTags) {
      createPayload.default_tags = nextDefaultTags;
    }

    const createResult = await props.onCreateInventory(createPayload);

    if (createResult.ok) {
      closeCreateForm();
      return;
    }

    if (createResult.reason === "conflict") {
      setShowShortNameField(true);
      setFormError("That collection name needs a different short name. Edit it below and try again.");
    }
  }

  function toggleChangeCollection() {
    if (!otherInventories.length) {
      return;
    }

    props.onCollectionMenuOpenChange(!changeCollectionOpen);
    setCreateFormOpen(false);
    resetCreateForm();
  }

  function handleSelectInventory(inventorySlug: string) {
    props.onCollectionMenuOpenChange(false);
    props.onSelectInventory(inventorySlug);
  }

  function renderCreateForm() {
    return (
      <form className="form-section inventory-create-form" onSubmit={handleCreateSubmit}>
        <div className="inventory-create-grid">
          <label className="field">
            <span>Collection name</span>
            <input
              className="text-input"
              data-autofocus
              onChange={(event) => handleDisplayNameChange(event.target.value)}
              placeholder="e.g. Trade Binder"
              value={displayName}
            />
          </label>

          {showShortNameField ? (
            <label className="field">
              <span>Short name</span>
              <input
                className="text-input"
                onChange={(event) => handleSlugChange(event.target.value)}
                placeholder="trade-binder"
                value={slug}
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
              onChange={(event) => handleDescriptionChange(event.target.value)}
              placeholder="Add a short description for this collection."
              value={description}
            />
          </label>

          <label className="field">
            <span>Default location</span>
            <input
              className="text-input"
              onChange={(event) => handleDefaultLocationChange(event.target.value)}
              placeholder="e.g. Trade Binder"
              value={defaultLocation}
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
              onChange={(event) => handleDefaultTagsChange(event.target.value)}
              placeholder="e.g. trade, staples"
              value={defaultTags}
            />
            <span className="field-hint field-hint-info">
              Items added to this collection will automatically include these tags.
            </span>
          </label>
        </div>

        {formError ? <p className="field-hint field-hint-error">{formError}</p> : null}

        <div className="inventory-create-actions">
          <button
            className="primary-button"
            disabled={props.createInventoryBusy}
            type="submit"
          >
            {props.createInventoryBusy ? "Creating..." : "Create Collection"}
          </button>
          <button
            className="secondary-button"
            disabled={props.createInventoryBusy}
            onClick={closeCreateForm}
            type="button"
          >
            Cancel
          </button>
        </div>

        <p className="panel-hint inventory-sidebar-note">
          Collections help separate personal, trade, deck, and project cards.
        </p>
      </form>
    );
  }

  const inventorySidebarPanelStyle =
    changeCollectionOpen && inventorySwitcherOverlayHeight > 0
      ? {
          ["--inventory-switcher-overlay-height" as string]: `${inventorySwitcherOverlayHeight}px`,
        }
      : undefined;

  return (
    <section
      className={
        changeCollectionOpen && props.collectionMenuInteractionEnabled
          ? "panel inventory-sidebar-panel inventory-sidebar-panel-switcher-open"
          : "panel inventory-sidebar-panel"
      }
      style={inventorySidebarPanelStyle}
    >
      {props.inventoryError && props.inventories.length && props.appShellState === "ready" ? (
        <p className="panel-error">Could not refresh the collection list right now.</p>
      ) : null}

      {props.appShellState === "loading" && props.inventories.length === 0 ? (
        <PanelState
          body="Looking for collections on this device."
          compact
          eyebrow="Collections"
          title="Loading collections"
          variant="loading"
        />
      ) : props.appShellState === "error" && props.inventories.length === 0 ? (
        <PanelState
          body="Collections could not be loaded right now. Refresh and try again."
          compact
          eyebrow="Collections"
          title="Collections unavailable"
          variant="error"
        />
      ) : currentInventory ? (
        <>
          <div className="inventory-sidebar-actions">
            <button
              className="secondary-button inventory-sidebar-action inventory-sidebar-action-support"
              onClick={openCreateForm}
              type="button"
            >
              <span
                aria-hidden="true"
                className="inventory-action-icon inventory-action-icon-create"
              />
              <span className="inventory-sidebar-action-content">
                <span className="inventory-sidebar-action-create-label">Create Collection</span>
                <span aria-hidden="true" className="inventory-sidebar-action-meta">
                  Add another deck, binder, or project space
                </span>
              </span>
            </button>
          </div>

          <div className="inventory-focus-block">
            <p className="section-kicker inventory-focus-kicker">Current Collection</p>
            <div className="inventory-switcher" ref={inventorySwitcherRef}>
              {otherInventories.length ? (
                <button
                  aria-controls={inventorySwitcherId}
                  aria-expanded={changeCollectionOpen}
                  className={
                    changeCollectionOpen
                      ? "inventory-button inventory-focus-trigger inventory-button-active"
                      : "inventory-button inventory-focus-trigger"
                  }
                  onClick={toggleChangeCollection}
                  type="button"
                >
                  <span className="inventory-focus-trigger-main">
                    <span className="inventory-focus-trigger-copygroup">
                      <strong className="inventory-focus-title">
                        {currentInventory.display_name}
                      </strong>
                      <span className="inventory-focus-trigger-summary">
                        {getOtherInventoryCountLabel(otherInventories.length)}
                      </span>
                    </span>
                    <span aria-hidden="true" className="inventory-focus-trigger-affordance">
                      <span className="inventory-focus-trigger-label">Switch</span>
                      <span
                        className={
                          changeCollectionOpen
                            ? "inventory-focus-trigger-indicator inventory-focus-trigger-indicator-open"
                            : "inventory-focus-trigger-indicator"
                        }
                      >
                        ▾
                      </span>
                    </span>
                  </span>
                </button>
              ) : (
                <div className="inventory-focus-card">
                  <div className="inventory-focus-card-main">
                    <strong className="inventory-focus-title">
                      {currentInventory.display_name}
                    </strong>
                    <span className="inventory-focus-trigger-summary">
                      {getOtherInventoryCountLabel(otherInventories.length)}
                    </span>
                  </div>
                </div>
              )}

              {changeCollectionOpen && props.collectionMenuInteractionEnabled ? (
                <div
                  className="inventory-switcher-list"
                  id={inventorySwitcherId}
                  ref={inventorySwitcherListRef}
                >
                  {otherInventories.map((inventory, index) => (
                    <InventorySwitcherOption
                      key={inventory.slug}
                      autoFocus={index === 0}
                      inventory={inventory}
                      onSelect={handleSelectInventory}
                    />
                  ))}
                </div>
              ) : null}
            </div>
          </div>

        </>
      ) : props.appShellState === "bootstrap_available" ? (
        <>
          <PanelState
            body="Create your personal collection to start adding cards, tracking value, and keeping everything organized."
            compact
            eyebrow="Collections"
            title="Start your first collection"
          />
          <div className="inventory-sidebar-actions inventory-sidebar-actions-empty">
            <button
              className="primary-button inventory-sidebar-action inventory-sidebar-action-create"
              disabled={props.createInventoryBusy}
              onClick={openCreateForm}
              type="button"
            >
              <span
                aria-hidden="true"
                className="inventory-action-icon inventory-action-icon-create"
              />
              <span className="inventory-sidebar-action-create-label">
                {props.createInventoryBusy ? "Creating..." : "Create Collection"}
              </span>
            </button>
          </div>
          <p className="panel-hint inventory-sidebar-note">
            You can split cards into more collections later.
          </p>
        </>
      ) : (
        <>
          <PanelState
            body="You are signed in, but no collections are shared with this account yet. Ask an owner to grant access."
            compact
            eyebrow="Collections"
            title="Collection access needed"
          />
          <p className="panel-hint inventory-sidebar-note">
            Search and inventory tools unlock once you can read at least one collection.
          </p>
        </>
      )}

      <ModalDialog
        isOpen={createFormOpen}
        kicker="Collection Setup"
        onClose={closeCreateForm}
        subtitle="Give the collection a clear name and add an optional description."
        title="Create Collection"
      >
        {renderCreateForm()}
      </ModalDialog>
    </section>
  );
}
