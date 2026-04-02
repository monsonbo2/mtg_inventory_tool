import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import type { AddInventoryItemRequest, CatalogSearchRow, FinishValue } from "../types";
import type { SearchCardGroup } from "../searchResultHelpers";
import type { AsyncStatus, NoticeTone } from "../uiTypes";
import {
  formatPrintingOptionLabel,
  summarizePreviewPrintings,
} from "../searchResultHelpers";
import { FINISH_OPTIONS, formatFinishLabel, parseTags, toUserMessage } from "../uiHelpers";
import { CardThumbnail } from "./ui/CardThumbnail";

export function SearchResultCard(props: {
  group: SearchCardGroup;
  busyPrintingId: string | null;
  canAdd: boolean;
  onLoadPrintings: (group: SearchCardGroup) => Promise<CatalogSearchRow[]>;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [printings, setPrintings] = useState<CatalogSearchRow[]>(props.group.previewPrintings);
  const [printingStatus, setPrintingStatus] = useState<AsyncStatus>("idle");
  const [printingError, setPrintingError] = useState<string | null>(null);
  const [hasLoadedExactPrintings, setHasLoadedExactPrintings] = useState(false);
  const [selectedPrintingId, setSelectedPrintingId] = useState<string | null>(
    props.group.previewPrintings[0]?.scryfall_id || null,
  );
  const [quantity, setQuantity] = useState("1");
  const [finish, setFinish] = useState<FinishValue>(props.group.previewPrintings[0]?.finishes[0] || "normal");
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

  useEffect(() => {
    setExpanded(false);
    setPrintings(props.group.previewPrintings);
    setPrintingStatus("idle");
    setPrintingError(null);
    setHasLoadedExactPrintings(false);
    setSelectedPrintingId(props.group.previewPrintings[0]?.scryfall_id || null);
    setQuantity("1");
    setFinish(props.group.previewPrintings[0]?.finishes[0] || "normal");
    setLocation("");
    setNotes("");
    setTags("");
    setRecentlyAdded(false);
  }, [props.group.groupId]);

  const activePrinting =
    printings.find((printing) => printing.scryfall_id === selectedPrintingId) || printings[0] || null;
  const busy =
    props.busyPrintingId !== null &&
    printings.some((printing) => printing.scryfall_id === props.busyPrintingId);

  useEffect(() => {
    if (!activePrinting) {
      return;
    }

    if (!activePrinting.finishes.includes(finish)) {
      setFinish(activePrinting.finishes[0] || "normal");
      setRecentlyAdded(false);
    }
  }, [activePrinting, finish]);

  useEffect(() => {
    if (!activePrinting && printings.length) {
      setSelectedPrintingId(printings[0].scryfall_id);
    }
  }, [activePrinting, printings]);

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
  const addButtonLabel = busy
    ? "Adding..."
    : recentlyAdded
      ? "Added"
      : !props.canAdd
        ? "Select inventory"
        : quantityIsValid
          ? "Add to inventory"
          : "Enter valid qty";
  const availableFinishes = FINISH_OPTIONS.filter((option) =>
    activePrinting?.finishes.includes(option.value),
  );
  const selectedPrintingSummary = activePrinting
    ? `${activePrinting.set_name} · #${activePrinting.collector_number} · ${activePrinting.lang.toUpperCase()}`
    : "Choose the exact printing to enable quick add.";

  async function loadPrintings() {
    setPrintingStatus("loading");
    setPrintingError(null);

    try {
      const nextPrintings = await props.onLoadPrintings(props.group);
      setPrintings(nextPrintings);
      setSelectedPrintingId((current) => current || nextPrintings[0]?.scryfall_id || null);
      setHasLoadedExactPrintings(true);
      setPrintingStatus("ready");
    } catch (error) {
      setPrintingStatus("error");
      setPrintingError(toUserMessage(error, "Could not load printings for this card."));
    }
  }

  async function handleToggleExpanded() {
    const nextExpanded = !expanded;
    setExpanded(nextExpanded);

    if (nextExpanded && !hasLoadedExactPrintings) {
      await loadPrintings();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!props.canAdd) {
      props.onNotice("Select an inventory before adding a card.");
      return;
    }

    if (!activePrinting) {
      props.onNotice("Choose an exact printing before adding the card.", "error");
      return;
    }

    if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) {
      props.onNotice("Enter a whole-number quantity greater than 0.", "error");
      return;
    }

    const didAdd = await props.onAdd({
      scryfall_id: activePrinting.scryfall_id,
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
          imageUrl={activePrinting?.image_uri_small || props.group.image_uri_small}
          imageUrlLarge={activePrinting?.image_uri_normal || props.group.image_uri_normal}
          name={props.group.name}
          variant="search"
        />

        <div className="card-hero-body">
          <div className="result-card-header">
            <div>
              <h3>{props.group.name}</h3>
              <p className="result-card-subtitle">{selectedPrintingSummary}</p>
            </div>
            <span className="rarity-pill">{props.group.rarity || "unknown"}</span>
          </div>

          <p className="search-result-summary">{summarizePreviewPrintings(props.group)}</p>

          <div className="tag-row">
            {props.group.previewPrintings.slice(0, 3).map((printing) => (
              <span className="tag-chip subdued" key={printing.scryfall_id}>
                {printing.set_code.toUpperCase()}
              </span>
            ))}
            {props.group.previewPrintings.length > 3 ? (
              <span className="tag-chip subdued">
                +{props.group.previewPrintings.length - 3} more sampled
              </span>
            ) : null}
          </div>

          <button
            aria-expanded={expanded}
            className="secondary-button search-result-toggle"
            onClick={() => {
              void handleToggleExpanded();
            }}
            type="button"
          >
            {expanded ? "Hide printings" : "Choose printing"}
          </button>
        </div>
      </div>

      {expanded ? (
        <form className="add-card-form" onSubmit={handleSubmit}>
          <div className="form-section">
            <div className="form-section-header">
              <strong>Quick add</strong>
              <span>
                {activePrinting
                  ? `${printings.length} printings available`
                  : "Loading the available printings"}
              </span>
            </div>

            {printingStatus === "loading" ? (
              <p className="field-hint field-hint-info">
                Loading exact printings for {props.group.name}...
              </p>
            ) : printingStatus === "error" ? (
              <div className="search-printing-state">
                <p className="field-hint field-hint-error">
                  {printingError || "Could not load printings for this card."}
                </p>
                <button
                  className="secondary-button"
                  onClick={() => {
                    void loadPrintings();
                  }}
                  type="button"
                >
                  Retry printing lookup
                </button>
              </div>
            ) : (
              <div className="search-result-quick-add-grid">
                <label className="field search-printing-field">
                  <span>Printing</span>
                  <select
                    className="text-input"
                    disabled={busy}
                    onChange={(event) => {
                      setSelectedPrintingId(event.target.value);
                      setRecentlyAdded(false);
                    }}
                    value={activePrinting?.scryfall_id || ""}
                  >
                    {printings.map((printing) => (
                      <option key={printing.scryfall_id} value={printing.scryfall_id}>
                        {formatPrintingOptionLabel(printing)}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="field">
                  <span>Qty</span>
                  <input
                    className="text-input"
                    disabled={busy || !props.canAdd}
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
                    disabled={busy || !props.canAdd || availableFinishes.length <= 1}
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
            )}

            {activePrinting ? (
              <div className="tag-row search-printing-meta">
                <span className="tag-chip">{activePrinting.set_code.toUpperCase()}</span>
                <span className="tag-chip">{activePrinting.lang.toUpperCase()}</span>
                {activePrinting.finishes.map((value) => (
                  <span className="tag-chip subdued" key={value}>
                    {formatFinishLabel(value)}
                  </span>
                ))}
              </div>
            ) : null}
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
                disabled={busy || !props.canAdd || printingStatus === "loading"}
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
                disabled={busy || !props.canAdd || printingStatus === "loading"}
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
                disabled={busy || !props.canAdd || printingStatus === "loading"}
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
              Added successfully. You can keep this group open and add another printing.
            </p>
          ) : null}

          <button
            className="primary-button"
            disabled={
              busy ||
              !props.canAdd ||
              !quantityIsValid ||
              printingStatus === "loading" ||
              !activePrinting
            }
            type="submit"
          >
            {addButtonLabel}
          </button>
        </form>
      ) : null}
    </article>
  );
}
