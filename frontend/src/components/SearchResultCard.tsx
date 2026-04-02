import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type { AddInventoryItemRequest, CatalogSearchRow, FinishValue } from "../types";
import type { NoticeTone } from "../uiTypes";
import { FINISH_OPTIONS, formatFinishLabel, parseTags } from "../uiHelpers";
import { CardThumbnail } from "./ui/CardThumbnail";

export function SearchResultCard(props: {
  result: CatalogSearchRow;
  busy: boolean;
  canAdd: boolean;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  const [quantity, setQuantity] = useState("1");
  const [finish, setFinish] = useState<FinishValue>(props.result.finishes[0] || "normal");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [recentlyAdded, setRecentlyAdded] = useState(false);

  useEffect(() => {
    if (!recentlyAdded) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setRecentlyAdded(false);
    }, 1800);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [recentlyAdded]);

  const parsedQuantity = Number.parseInt(quantity, 10);
  const parsedTags = parseTags(tags);
  const trimmedLocation = location.trim();
  const trimmedNotes = notes.trim();
  const quantityIsValid = Number.isInteger(parsedQuantity) && parsedQuantity > 0;
  const optionalDetailSummary =
    [
      trimmedLocation ? `Location: ${trimmedLocation}` : null,
      parsedTags.length ? `${parsedTags.length} tag${parsedTags.length === 1 ? "" : "s"}` : null,
      trimmedNotes ? "Note ready" : null,
    ].filter(Boolean).join(" · ") || "No optional details yet";
  const addButtonLabel = props.busy
    ? "Adding..."
    : recentlyAdded
      ? "Added"
      : !props.canAdd
        ? "Select inventory"
        : quantityIsValid
          ? "Add to inventory"
          : "Enter valid qty";
  const availableFinishes = FINISH_OPTIONS.filter((option) => props.result.finishes.includes(option.value));

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!props.canAdd) {
      props.onNotice("Select an inventory before adding a card.");
      return;
    }

    if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) {
      props.onNotice("Enter a whole-number quantity greater than 0.", "error");
      return;
    }

    const didAdd = await props.onAdd({
      scryfall_id: props.result.scryfall_id,
      quantity: parsedQuantity,
      finish,
      location: trimmedLocation || undefined,
      notes: trimmedNotes || null,
      tags: parsedTags,
    });
    if (didAdd) {
      setRecentlyAdded(true);
    }
  }

  return (
    <article className="result-card">
      <div className="card-hero">
        <CardThumbnail
          imageUrl={props.result.image_uri_small}
          imageUrlLarge={props.result.image_uri_normal}
          name={props.result.name}
          variant="search"
        />

        <div className="card-hero-body">
          <div className="result-card-header">
            <div>
              <h3>{props.result.name}</h3>
              <p className="result-card-subtitle">
                {props.result.set_name} · #{props.result.collector_number}
              </p>
            </div>
            <span className="rarity-pill">{props.result.rarity || "unknown"}</span>
          </div>

          <div className="tag-row">
            <span className="tag-chip">{props.result.set_code.toUpperCase()}</span>
            <span className="tag-chip">{props.result.lang.toUpperCase()}</span>
            {props.result.finishes.map((value) => (
              <span className="tag-chip subdued" key={value}>
                {formatFinishLabel(value)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <form className="add-card-form" onSubmit={handleSubmit}>
        <div className="form-section">
          <div className="form-section-header">
            <strong>Quick add</strong>
            <span>
              {quantityIsValid
                ? `${parsedQuantity}x ${formatFinishLabel(finish)}`
                : "Choose quantity and finish"}
            </span>
          </div>

          <div className="mini-grid">
            <label className="field">
              <span>Qty</span>
              <input
                className="text-input"
                disabled={props.busy || !props.canAdd}
                min="1"
                onChange={(event) => {
                  setQuantity(event.target.value);
                  setRecentlyAdded(false);
                }}
                type="number"
                value={quantity}
              />
            </label>

            <label className="field">
              <span>Finish</span>
              <select
                className="text-input"
                disabled={props.busy || !props.canAdd}
                onChange={(event) => {
                  setFinish(event.target.value as FinishValue);
                  setRecentlyAdded(false);
                }}
                value={finish}
              >
                {availableFinishes.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="form-section form-section-muted">
          <div className="form-section-header">
            <strong>Optional row details</strong>
            <span>{optionalDetailSummary}</span>
          </div>

          <label className="field">
            <span>Location</span>
            <input
              className="text-input"
              disabled={props.busy || !props.canAdd}
              onChange={(event) => {
                setLocation(event.target.value);
                setRecentlyAdded(false);
              }}
              placeholder="Red Binder"
              value={location}
            />
          </label>

          <label className="field">
            <span>Tags</span>
            <input
              className="text-input"
              disabled={props.busy || !props.canAdd}
              onChange={(event) => {
                setTags(event.target.value);
                setRecentlyAdded(false);
              }}
              placeholder="burn, trade"
              value={tags}
            />
          </label>

          <label className="field">
            <span>Notes</span>
            <textarea
              className="text-area"
              disabled={props.busy || !props.canAdd}
              onChange={(event) => {
                setNotes(event.target.value);
                setRecentlyAdded(false);
              }}
              placeholder="Optional add-note for the row"
              rows={3}
              value={notes}
            />
          </label>
        </div>

        {!quantityIsValid ? (
          <p className="field-hint field-hint-error">
            Enter a whole-number quantity greater than 0.
          </p>
        ) : recentlyAdded ? (
          <p className="field-hint field-hint-success">
            Added successfully. You can adjust the form and add another copy.
          </p>
        ) : null}

        <button
          className="primary-button"
          disabled={props.busy || !props.canAdd || !quantityIsValid}
          type="submit"
        >
          {addButtonLabel}
        </button>
      </form>
    </article>
  );
}
