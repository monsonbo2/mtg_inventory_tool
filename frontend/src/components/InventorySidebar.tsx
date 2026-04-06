import { useEffect, useState } from "react";

import type { InventoryCreateRequest, InventorySummary } from "../types";
import { normalizeInventorySlugInput, normalizeOptionalText } from "../uiHelpers";
import type { AppShellState, AsyncStatus, InventoryCreateResult } from "../uiTypes";
import { ModalDialog } from "./ui/ModalDialog";
import { PanelState } from "./ui/PanelState";

function getInventoryCountLabel(availableCount: number) {
  return availableCount === 1 ? "1 collection" : `${availableCount} collections`;
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
        <span>
          {props.inventory.item_rows} rows · {props.inventory.total_cards} cards
        </span>
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
      data-autofocus={props.autoFocus ? "true" : undefined}
      onClick={() => props.onSelect(props.inventory.slug)}
      type="button"
    >
      <span className="inventory-switcher-option-name">{props.inventory.display_name}</span>
      <span className="inventory-switcher-option-meta">
        {props.inventory.item_rows} rows · {props.inventory.total_cards} cards
      </span>
    </button>
  );
}

export function InventorySidebar(props: {
  appShellState: AppShellState;
  bootstrapInventoryBusy: boolean;
  createInventoryBusy: boolean;
  inventories: InventorySummary[];
  selectedInventory: string | null;
  selectedInventoryRow: InventorySummary | null;
  inventoryStatus: AsyncStatus;
  inventoryError: string | null;
  onBootstrapInventory: () => Promise<boolean>;
  onCreateInventory: (payload: InventoryCreateRequest) => Promise<InventoryCreateResult>;
  onSelectInventory: (inventorySlug: string) => void;
}) {
  const [createFormOpen, setCreateFormOpen] = useState(false);
  const [changeCollectionOpen, setChangeCollectionOpen] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [slug, setSlug] = useState("");
  const [showShortNameField, setShowShortNameField] = useState(false);
  const [description, setDescription] = useState("");
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

  useEffect(() => {
    setChangeCollectionOpen(false);
  }, [props.selectedInventory]);

  useEffect(() => {
    if (props.appShellState !== "ready") {
      setCreateFormOpen(false);
      setChangeCollectionOpen(false);
      resetCreateForm();
    }
  }, [props.appShellState]);

  function resetCreateForm() {
    setDisplayName("");
    setSlug("");
    setShowShortNameField(false);
    setDescription("");
    setSlugTouched(false);
    setFormError(null);
  }

  function openCreateForm() {
    setCreateFormOpen(true);
    setChangeCollectionOpen(false);
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

  async function handleCreateSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const nextDisplayName = displayName.trim();
    const nextSlug = normalizeInventorySlugInput(slug);

    if (!nextDisplayName) {
      setFormError("Enter a collection name before creating it.");
      return;
    }

    if (!nextSlug) {
      setFormError("Enter a short name using letters, numbers, or hyphens.");
      return;
    }

    const createResult = await props.onCreateInventory({
      display_name: nextDisplayName,
      slug: nextSlug,
      description: normalizeOptionalText(description),
    });

    if (createResult.ok) {
      closeCreateForm();
      return;
    }

    if (createResult.reason === "conflict") {
      setShowShortNameField(true);
      setFormError("That collection name needs a different short name. Edit it below and try again.");
    }
  }

  function openChangeCollection() {
    setChangeCollectionOpen(true);
    setCreateFormOpen(false);
    resetCreateForm();
  }

  function handleSelectInventory(inventorySlug: string) {
    setChangeCollectionOpen(false);
    props.onSelectInventory(inventorySlug);
  }

  function closeChangeCollection() {
    setChangeCollectionOpen(false);
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
          You need <code>editor</code> or <code>admin</code> access to create collections.
        </p>
      </form>
    );
  }

  return (
    <section className="panel inventory-sidebar-panel">
      {props.inventoryError && props.inventories.length && props.appShellState === "ready" ? (
        <p className="panel-error">{props.inventoryError}</p>
      ) : null}

      {props.appShellState === "loading" && props.inventories.length === 0 ? (
        <PanelState
          body="Checking which collections are available to this workspace."
          compact
          title="Loading collections"
          variant="loading"
        />
      ) : props.appShellState === "auth_required" ? (
        <PanelState
          body="Sign in through the shared-service deployment before loading collections."
          compact
          title="Authentication required"
          variant="error"
        />
      ) : props.appShellState === "forbidden" ? (
        <PanelState
          body="This account is signed in but does not currently have permission to view any collections."
          compact
          title="Collection access blocked"
          variant="error"
        />
      ) : props.appShellState === "error" && props.inventories.length === 0 ? (
        <PanelState
          body={props.inventoryError || "Could not load collections right now."}
          compact
          title="Collections unavailable"
          variant="error"
        />
      ) : currentInventory ? (
        <>
          <div className="inventory-focus-block">
            <p className="section-kicker inventory-focus-kicker">Current Collection</p>
            <div className="inventory-focus-card">
              <InventoryCardSummary inventory={currentInventory} />
            </div>
          </div>

          <div className="inventory-sidebar-actions">
            {otherInventories.length ? (
              <button
                aria-haspopup="dialog"
                className="secondary-button inventory-sidebar-action inventory-sidebar-action-switch"
                onClick={openChangeCollection}
                type="button"
              >
                <span className="inventory-sidebar-action-content">
                  <span className="inventory-sidebar-action-switch-label">
                    Change Collection
                  </span>
                  <span className="inventory-sidebar-action-meta">
                    {getInventoryCountLabel(props.inventories.length)} available
                  </span>
                </span>
              </button>
            ) : null}

            <button
              className="primary-button inventory-sidebar-action inventory-sidebar-action-create"
              onClick={openCreateForm}
              type="button"
            >
              <span
                aria-hidden="true"
                className="inventory-action-icon inventory-action-icon-create"
              />
              <span className="inventory-sidebar-action-create-label">Create Collection</span>
            </button>
          </div>

        </>
      ) : (
        <>
          <PanelState
            body="Set up your default collection to unlock search, collection, and activity views for this account."
            compact
            title="No visible collections"
          />
          <div className="inventory-sidebar-actions inventory-sidebar-actions-empty">
            <button
              className="primary-button inventory-sidebar-action inventory-sidebar-action-create"
              disabled={props.bootstrapInventoryBusy}
              onClick={() => {
                void props.onBootstrapInventory();
              }}
              type="button"
            >
              <span
                aria-hidden="true"
                className="inventory-action-icon inventory-action-icon-create"
              />
              <span className="inventory-sidebar-action-create-label">
                {props.bootstrapInventoryBusy ? "Setting Up..." : "Set Up My Collection"}
              </span>
            </button>
          </div>
          <p className="panel-hint inventory-sidebar-note">
            This creates or reopens your personal default collection for the current signed-in account.
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

      <ModalDialog
        isOpen={changeCollectionOpen}
        kicker="Collections"
        onClose={closeChangeCollection}
        subtitle="Choose the collection you want to view and edit."
        title="Change Collection"
      >
        <div className="inventory-switcher-modal-list">
          {otherInventories.map((inventory, index) => (
            <InventorySwitcherOption
              key={inventory.slug}
              autoFocus={index === 0}
              inventory={inventory}
              onSelect={handleSelectInventory}
            />
          ))}
        </div>
      </ModalDialog>
    </section>
  );
}
