import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import type {
  FinishValue,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
} from "../types";
import type { ItemMutationAction, NoticeTone } from "../uiTypes";
import {
  decimalToNumber,
  equalStringArrays,
  formatFinishLabel,
  formatLanguageCode,
  formatUsd,
  getAvailableFinishesForOwnedRow,
  getBusyMessage,
  normalizeOptionalText,
  parseTags,
} from "../uiHelpers";
import { CardThumbnail } from "./ui/CardThumbnail";

export function CompactInventoryList(props: {
  items: OwnedInventoryRow[];
  expandedItemId: number | null;
  busyItem: { itemId: number; action: ItemMutationAction } | null;
  onExpandedItemChange: (itemId: number | null) => void;
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<void>;
  onDelete: (itemId: number, cardName: string) => Promise<void>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  return (
    <div className="compact-collection-list">
      {props.items.map((item) => (
        <CompactInventoryRow
          busyAction={props.busyItem?.itemId === item.item_id ? props.busyItem.action : null}
          isExpanded={props.expandedItemId === item.item_id}
          item={item}
          key={item.item_id}
          onDelete={props.onDelete}
          onNotice={props.onNotice}
          onPatch={props.onPatch}
          onToggle={() =>
            props.onExpandedItemChange(
              props.expandedItemId === item.item_id ? null : item.item_id,
            )
          }
        />
      ))}
    </div>
  );
}

function CompactInventoryRow(props: {
  item: OwnedInventoryRow;
  isExpanded: boolean;
  busyAction: ItemMutationAction | null;
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<void>;
  onDelete: (itemId: number, cardName: string) => Promise<void>;
  onNotice: (message: string, tone?: NoticeTone) => void;
  onToggle: () => void;
}) {
  const [quantity, setQuantity] = useState(String(props.item.quantity));
  const [finish, setFinish] = useState<FinishValue>(props.item.finish);
  const [location, setLocation] = useState(props.item.location || "");
  const [notes, setNotes] = useState(props.item.notes || "");
  const [tags, setTags] = useState(props.item.tags.join(", "));

  useEffect(() => {
    setQuantity(String(props.item.quantity));
    setFinish(props.item.finish);
    setLocation(props.item.location || "");
    setNotes(props.item.notes || "");
    setTags(props.item.tags.join(", "));
  }, [
    props.isExpanded,
    props.item.finish,
    props.item.item_id,
    props.item.location,
    props.item.notes,
    props.item.quantity,
    props.item.tags,
  ]);

  async function saveQuantity() {
    if (!quantityIsValid) {
      props.onNotice("Enter a whole-number quantity greater than 0.", "error");
      return;
    }
    await props.onPatch(props.item.item_id, "quantity", { quantity: parsedQuantity });
  }

  async function saveFinish() {
    await props.onPatch(props.item.item_id, "finish", { finish });
  }

  async function saveLocation() {
    const trimmed = location.trim();
    await props.onPatch(
      props.item.item_id,
      "location",
      trimmed ? { location: trimmed } : { clear_location: true },
    );
  }

  async function saveNotes() {
    const trimmed = notes.trim();
    await props.onPatch(
      props.item.item_id,
      "notes",
      trimmed ? { notes: trimmed } : { clear_notes: true },
    );
  }

  async function saveTags() {
    const parsedTags = parseTags(tags);
    await props.onPatch(
      props.item.item_id,
      "tags",
      parsedTags.length ? { tags: parsedTags } : { clear_tags: true },
    );
  }

  async function handleDelete() {
    const confirmed = window.confirm(
      `Remove ${props.item.name} from the selected collection?`,
    );
    if (!confirmed) {
      return;
    }
    await props.onDelete(props.item.item_id, props.item.name);
  }

  const isBusy = props.busyAction !== null;
  const parsedQuantity = Number.parseInt(quantity, 10);
  const quantityIsValid = Number.isInteger(parsedQuantity) && parsedQuantity > 0;
  const quantityHasError =
    quantity.trim() !== String(props.item.quantity) && !quantityIsValid;
  const quantityDirty = quantityIsValid && parsedQuantity !== props.item.quantity;
  const finishDirty = finish !== props.item.finish;
  const locationDirty =
    normalizeOptionalText(location) !== normalizeOptionalText(props.item.location);
  const notesDirty =
    normalizeOptionalText(notes) !== normalizeOptionalText(props.item.notes);
  const currentTags = parseTags(tags);
  const tagsDirty = !equalStringArrays(currentTags, props.item.tags);
  const hasDirtyChanges =
    quantityDirty || finishDirty || locationDirty || notesDirty || tagsDirty;
  const busyMessage = props.busyAction ? getBusyMessage(props.busyAction) : null;
  const availableFinishes = getAvailableFinishesForOwnedRow(
    props.item.finish,
    props.item.allowed_finishes,
  );
  const finishEditorLocked = availableFinishes.length <= 1;
  const finishHint =
    availableFinishes.length === 1
      ? `This printing only supports ${formatFinishLabel(availableFinishes[0])}.`
      : `Available: ${availableFinishes.map((value) => formatFinishLabel(value)).join(", ")}.`;
  const statusMessage = busyMessage
    ? busyMessage
    : quantityHasError
      ? "Enter a whole-number quantity greater than 0."
      : hasDirtyChanges
        ? "Unsaved changes"
        : "All changes saved";

  return (
    <article className={isBusy ? "compact-row compact-row-busy" : "compact-row"}>
      <div className="compact-row-main">
        <div className="compact-row-left">
          <CardThumbnail
            imageUrl={props.item.image_uri_small}
            imageUrlLarge={props.item.image_uri_normal}
            name={props.item.name}
            variant="owned"
          />

          <div className="compact-row-copy">
            <h3>{props.item.name}</h3>
            <p className="result-card-subtitle">
              {props.item.set_name} · #{props.item.collector_number}
            </p>
            <div className="tag-row compact-row-tags">
              <span className="tag-chip">{props.item.set_code.toUpperCase()}</span>
              <span className="tag-chip subdued">{props.item.condition_code}</span>
              <span className="tag-chip subdued">{formatLanguageCode(props.item.language_code)}</span>
            </div>
          </div>
        </div>

        <div className="compact-row-stats">
          <CompactStat label="Quantity" value={String(props.item.quantity)} />
          <CompactStat label="Finish" value={formatFinishLabel(props.item.finish)} />
          <CompactStat label="Location" value={props.item.location || "Not set"} />
          <CompactStat
            label="Value"
            value={formatUsd(decimalToNumber(props.item.est_value))}
          />
        </div>

        <button
          aria-expanded={props.isExpanded}
          aria-label={`${props.isExpanded ? "Close editor for" : "Edit"} ${props.item.name}`}
          className="secondary-button compact-row-toggle"
          onClick={props.onToggle}
          type="button"
        >
          {props.isExpanded ? "Close" : "Edit"}
        </button>
      </div>

      {props.isExpanded ? (
        <div className="compact-row-editor">
          <div className="editor-section-header">
            <strong>Inline edits</strong>
            <span
              className={
                busyMessage
                  ? "row-status-label row-status-busy"
                  : quantityHasError
                    ? "row-status-label row-status-error"
                    : hasDirtyChanges
                      ? "row-status-label row-status-dirty"
                      : "row-status-label row-status-ready"
              }
            >
              {statusMessage}
            </span>
          </div>

          <div className="editor-grid compact-row-editor-grid">
            <InlineEditor
              busy={props.busyAction === "quantity"}
              dirty={quantityDirty}
              disabled={isBusy || !quantityDirty}
              invalid={quantityHasError}
              label="Quantity"
              onSave={saveQuantity}
            >
              <input
                className="text-input"
                disabled={isBusy}
                min="1"
                onChange={(event) => setQuantity(event.target.value)}
                type="number"
                value={quantity}
              />
            </InlineEditor>

            <InlineEditor
              busy={props.busyAction === "finish"}
              dirty={finishDirty}
              disabled={isBusy || !finishDirty || finishEditorLocked}
              hint={finishHint}
              hintTone="info"
              label="Finish"
              onSave={saveFinish}
            >
              <select
                className="text-input"
                disabled={isBusy || finishEditorLocked}
                onChange={(event) => setFinish(event.target.value as FinishValue)}
                value={finish}
              >
                {availableFinishes.map((value) => (
                  <option key={value} value={value}>
                    {formatFinishLabel(value)}
                  </option>
                ))}
              </select>
            </InlineEditor>

            <InlineEditor
              busy={props.busyAction === "location"}
              dirty={locationDirty}
              disabled={isBusy || !locationDirty}
              label="Location"
              onSave={saveLocation}
            >
              <input
                className="text-input"
                disabled={isBusy}
                onChange={(event) => setLocation(event.target.value)}
                placeholder="Row location"
                value={location}
              />
            </InlineEditor>

            <InlineEditor
              busy={props.busyAction === "tags"}
              dirty={tagsDirty}
              disabled={isBusy || !tagsDirty}
              label="Tags"
              onSave={saveTags}
            >
              <input
                className="text-input"
                disabled={isBusy}
                onChange={(event) => setTags(event.target.value)}
                placeholder="burn, trade"
                value={tags}
              />
            </InlineEditor>
          </div>

          <InlineEditor
            busy={props.busyAction === "notes"}
            dirty={notesDirty}
            disabled={isBusy || !notesDirty}
            label="Notes"
            onSave={saveNotes}
            wide
          >
            <textarea
              className="text-area"
              disabled={isBusy}
              onChange={(event) => setNotes(event.target.value)}
              rows={3}
              value={notes}
            />
          </InlineEditor>

          <div className="compact-row-footer">
            <div className="tag-row compact-row-footer-tags">
              {props.item.tags.length ? (
                props.item.tags.map((tag) => (
                  <span className="tag-chip" key={tag}>
                    {tag}
                  </span>
                ))
              ) : (
                <span className="muted-note">No saved tags</span>
              )}
            </div>

            <button
              className="danger-button"
              disabled={isBusy}
              onClick={() => {
                void handleDelete();
              }}
              type="button"
            >
              {props.busyAction === "delete" ? "Removing..." : "Remove row"}
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function InlineEditor(props: {
  label: string;
  children: ReactNode;
  onSave: () => Promise<void>;
  busy?: boolean;
  dirty?: boolean;
  invalid?: boolean;
  disabled?: boolean;
  hint?: string;
  hintTone?: "info" | "error" | "success";
  wide?: boolean;
}) {
  const className = props.wide
    ? props.dirty
      ? "field inline-editor inline-editor-dirty wide"
      : "field inline-editor wide"
    : props.dirty
      ? "field inline-editor inline-editor-dirty"
      : "field inline-editor";

  return (
    <label className={className}>
      <span>{props.label}</span>
      <div className="inline-editor-row">
        {props.children}
        <button
          className="secondary-button"
          disabled={props.disabled}
          onClick={() => {
            void props.onSave();
          }}
          type="button"
        >
          {props.busy
            ? "Saving..."
            : props.invalid
              ? "Fix value"
              : props.dirty
                ? "Save"
                : "Saved"}
        </button>
      </div>
      {props.hint ? (
        <p
          className={`field-hint ${
            props.hintTone === "error"
              ? "field-hint-error"
              : props.hintTone === "success"
                ? "field-hint-success"
                : "field-hint-info"
          }`}
        >
          {props.hint}
        </p>
      ) : null}
    </label>
  );
}

function CompactStat(props: { label: string; value: string }) {
  return (
    <div className="compact-row-stat">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}
