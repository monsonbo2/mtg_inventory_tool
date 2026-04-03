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
  formatMaybeCurrency,
  formatUsd,
  getAvailableFinishesForOwnedRow,
  getBusyMessage,
  normalizeOptionalText,
  parseTags,
  summarizeInlineText,
} from "../uiHelpers";
import { CardThumbnail } from "./ui/CardThumbnail";

export function OwnedItemCard(props: {
  item: OwnedInventoryRow;
  busyAction: ItemMutationAction | null;
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<void>;
  onDelete: (itemId: number, cardName: string) => Promise<void>;
  onNotice: (message: string, tone?: NoticeTone) => void;
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
    <article className={isBusy ? "owned-card owned-card-busy" : "owned-card"}>
      <div className="card-hero">
        <CardThumbnail
          imageUrl={props.item.image_uri_small}
          imageUrlLarge={props.item.image_uri_normal}
          name={props.item.name}
          variant="owned"
        />

        <div className="card-hero-body">
          <div className="owned-card-header">
            <div>
              <h3>{props.item.name}</h3>
              <p className="result-card-subtitle">
                {props.item.set_name} · #{props.item.collector_number}
              </p>
              <p
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
              </p>
            </div>
            <div className="owned-card-pricing">
              <strong>{formatUsd(decimalToNumber(props.item.est_value))}</strong>
              <span>{props.item.price_date || "No price date"}</span>
            </div>
          </div>

          <div className="tag-row">
            <span className="tag-chip">{props.item.set_code.toUpperCase()}</span>
            <span className="tag-chip subdued">{props.item.condition_code}</span>
            <span className="tag-chip subdued">{formatFinishLabel(props.item.finish)}</span>
            <span className="tag-chip subdued">{formatLanguageCode(props.item.language_code)}</span>
          </div>
        </div>
      </div>

      <div className="item-meta-grid">
        <MetaLine
          label="Unit price"
          value={formatMaybeCurrency(props.item.unit_price, props.item.currency)}
        />
        <MetaLine
          label="Acquisition"
          value={formatMaybeCurrency(
            props.item.acquisition_price,
            props.item.acquisition_currency,
          )}
        />
        <MetaLine label="Location" value={props.item.location || "Not set"} />
        <MetaLine
          label="Saved note"
          value={props.item.notes ? summarizeInlineText(props.item.notes, 40) : "No saved notes"}
        />
      </div>

      <div className="editor-section-header">
        <strong>Inline edits</strong>
        <span>{hasDirtyChanges ? "Save the highlighted changes below" : "Adjust any field below"}</span>
      </div>

      <div className="editor-grid">
        <InlineEditor
          dirty={quantityDirty}
          invalid={quantityHasError}
          disabled={isBusy || !quantityDirty}
          busy={props.busyAction === "quantity"}
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
          dirty={finishDirty}
          disabled={isBusy || !finishDirty || finishEditorLocked}
          busy={props.busyAction === "finish"}
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
          dirty={locationDirty}
          disabled={isBusy || !locationDirty}
          busy={props.busyAction === "location"}
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
          dirty={tagsDirty}
          disabled={isBusy || !tagsDirty}
          busy={props.busyAction === "tags"}
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
        dirty={notesDirty}
        disabled={isBusy || !notesDirty}
        busy={props.busyAction === "notes"}
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

      <div className="owned-card-footer">
        <div className="tag-row">
          {props.item.tags.length ? (
            props.item.tags.map((tag) => (
              <span className="tag-chip" key={tag}>
                {tag}
              </span>
            ))
          ) : (
            <span className="muted-note">No tags</span>
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

function MetaLine(props: { label: string; value: string }) {
  return (
    <div className="meta-line">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}
