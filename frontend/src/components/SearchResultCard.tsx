import { useEffect, useId, useState } from "react";
import type { FormEvent } from "react";

import type {
  AddInventoryItemRequest,
  CatalogPrintingLookupRow,
  FinishValue,
} from "../types";
import type { SearchCardGroup } from "../searchResultHelpers";
import type { AsyncStatus, NoticeTone } from "../uiTypes";
import {
  formatPrintingOptionLabel,
  summarizeSearchGroup,
} from "../searchResultHelpers";
import {
  FINISH_OPTIONS,
  formatFinishLabel,
  formatLanguageCode,
  parseTags,
  toUserMessage,
} from "../uiHelpers";
import { CardThumbnail } from "./ui/CardThumbnail";

const LANGUAGE_LABELS: Record<string, string> = {
  en: "English",
  ja: "Japanese",
  de: "German",
  fr: "French",
  it: "Italian",
  es: "Spanish",
  pt: "Portuguese",
  ru: "Russian",
  ko: "Korean",
  zhs: "Chinese (Simplified)",
  zht: "Chinese (Traditional)",
  ph: "Phyrexian",
};

export function SearchResultCard(props: {
  group: SearchCardGroup;
  busyPrintingId: string | null;
  canAdd: boolean;
  onLoadPrintings: (group: SearchCardGroup) => Promise<CatalogPrintingLookupRow[]>;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  const [printings, setPrintings] = useState<CatalogPrintingLookupRow[]>([]);
  const [printingStatus, setPrintingStatus] = useState<AsyncStatus>("idle");
  const [printingError, setPrintingError] = useState<string | null>(null);
  const [hasLoadedExactPrintings, setHasLoadedExactPrintings] = useState(false);
  const [selectedPrintingId, setSelectedPrintingId] = useState("");
  const [showLanguagePicker, setShowLanguagePicker] = useState(false);
  const [selectedLanguageCode, setSelectedLanguageCode] = useState("en");
  const [quantity, setQuantity] = useState("1");
  const [finish, setFinish] = useState<FinishValue>("normal");
  const [location, setLocation] = useState("");
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [recentlyAdded, setRecentlyAdded] = useState(false);
  const printingFieldId = useId();
  const languageFieldId = useId();

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
    setPrintings([]);
    setPrintingStatus("idle");
    setPrintingError(null);
    setHasLoadedExactPrintings(false);
    setSelectedPrintingId("");
    setShowLanguagePicker(false);
    setSelectedLanguageCode("en");
    setQuantity("1");
    setFinish("normal");
    setLocation("");
    setNotes("");
    setTags("");
    setRecentlyAdded(false);
  }, [props.group.groupId]);

  const activePrinting =
    printings.find((printing) => printing.scryfall_id === selectedPrintingId) || null;
  const busy = props.busyPrintingId !== null && props.busyPrintingId === selectedPrintingId;
  const availableLanguageCodes = Array.from(new Set(printings.map((printing) => printing.lang))).sort(
    (left, right) => {
      if (left === "en") {
        return -1;
      }
      if (right === "en") {
        return 1;
      }
      return left.localeCompare(right);
    },
  );
  const hasEnglishPrintings = availableLanguageCodes.includes("en");
  const hasOtherLanguages = availableLanguageCodes.some((languageCode) => languageCode !== "en");
  const visiblePrintings = showLanguagePicker
    ? printings.filter((printing) => printing.lang === selectedLanguageCode)
    : hasEnglishPrintings
      ? printings.filter((printing) => printing.lang === "en")
      : printings;

  useEffect(() => {
    if (!activePrinting) {
      setFinish("normal");
      return;
    }

    if (!activePrinting.finishes.includes(finish)) {
      setFinish(activePrinting.finishes[0] || "normal");
      setRecentlyAdded(false);
    }
  }, [activePrinting, finish]);

  useEffect(() => {
    if (!availableLanguageCodes.length) {
      setSelectedLanguageCode("en");
      return;
    }

    setSelectedLanguageCode((current) => {
      if (availableLanguageCodes.includes(current as (typeof availableLanguageCodes)[number])) {
        return current;
      }
      return hasEnglishPrintings ? "en" : availableLanguageCodes[0];
    });
  }, [availableLanguageCodes, hasEnglishPrintings]);

  useEffect(() => {
    if (!selectedPrintingId) {
      return;
    }

    if (!visiblePrintings.some((printing) => printing.scryfall_id === selectedPrintingId)) {
      setSelectedPrintingId("");
    }
  }, [selectedPrintingId, visiblePrintings]);

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
  const needsPrintingSelection = props.canAdd && !activePrinting;
  const printingsAvailableLabel = `${props.group.printingsCount} printing${
    props.group.printingsCount === 1 ? "" : "s"
  } available`;
  const addButtonLabel = busy
    ? "Adding..."
    : recentlyAdded
      ? "Added"
      : !props.canAdd
        ? "Select collection"
        : needsPrintingSelection
          ? "Select printing first"
        : quantityIsValid
          ? "Add to collection"
          : "Enter valid qty";
  const availableFinishes = FINISH_OPTIONS.filter((option) =>
    activePrinting?.finishes.includes(option.value),
  );
  const selectedPrintingSummary = activePrinting
    ? `${activePrinting.set_name} · #${activePrinting.collector_number} · ${activePrinting.lang.toUpperCase()}${
        activePrinting.is_default_add_choice ? " · Default add choice" : ""
      }`
    : "Choose a printing below before adding this card.";

  async function loadPrintings() {
    if (printingStatus === "loading") {
      return;
    }

    setPrintingStatus("loading");
    setPrintingError(null);

    try {
      const nextPrintings = await props.onLoadPrintings(props.group);
      const nextSelectedPrinting =
        nextPrintings.find((printing) => printing.scryfall_id === selectedPrintingId) ||
        nextPrintings.find((printing) => printing.is_default_add_choice) ||
        null;
      setPrintings(nextPrintings);
      setSelectedPrintingId(nextSelectedPrinting?.scryfall_id || "");
      setShowLanguagePicker(
        Boolean(nextSelectedPrinting && nextSelectedPrinting.lang !== "en"),
      );
      setSelectedLanguageCode(nextSelectedPrinting?.lang || "en");
      setHasLoadedExactPrintings(true);
      setPrintingStatus("ready");
    } catch (error) {
      setPrintingStatus("error");
      setPrintingError(toUserMessage(error, "Could not load printings for this card."));
    }
  }

  function ensurePrintingsLoaded() {
    if (!hasLoadedExactPrintings) {
      void loadPrintings();
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!props.canAdd) {
      props.onNotice("Select a collection before adding a card.");
      return;
    }

    if (!activePrinting) {
      props.onNotice("Choose a printing before adding this card.", "error");
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
      <form className="add-card-form" onSubmit={handleSubmit}>
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
            </div>

            <p className="search-result-summary">{summarizeSearchGroup(props.group)}</p>
          </div>

          <div className="search-result-hero-actions">
            <button
              className="primary-button search-result-add-button"
              disabled={busy || !props.canAdd || !quantityIsValid || !activePrinting}
              type="submit"
            >
              {addButtonLabel}
            </button>
          </div>
        </div>

        <div className="form-section">
          <div className="form-section-header">
            <strong>Quick add</strong>
          </div>

          <div className="search-result-quick-add-grid">
            <div className="field search-printing-field">
              <label htmlFor={printingFieldId}>Printing</label>
              <select
                aria-label="Printing"
                className="text-input"
                disabled={busy}
                id={printingFieldId}
                onChange={(event) => {
                  setSelectedPrintingId(event.target.value);
                  setRecentlyAdded(false);
                }}
                onFocus={ensurePrintingsLoaded}
                value={selectedPrintingId}
              >
                <option value="">{printingsAvailableLabel}</option>
                {visiblePrintings.map((printing) => (
                  <option key={printing.scryfall_id} value={printing.scryfall_id}>
                    {formatPrintingOptionLabel(printing)}
                    {printing.is_default_add_choice ? " · Default choice" : ""}
                  </option>
                ))}
              </select>
            </div>

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
                disabled={
                  busy || !props.canAdd || !activePrinting || availableFinishes.length <= 1
                }
                onChange={(event) => {
                  setFinish(event.target.value as FinishValue);
                  setRecentlyAdded(false);
                }}
                value={finish}
              >
                {!activePrinting ? <option value="normal">Choose printing first</option> : null}
                {availableFinishes.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            {hasLoadedExactPrintings && hasOtherLanguages && !showLanguagePicker ? (
              <div className="search-printing-helper">
                <button
                  className="field-link-button"
                  onClick={() => {
                    setShowLanguagePicker(true);
                    setRecentlyAdded(false);
                  }}
                  type="button"
                >
                  Other languages available
                </button>
              </div>
            ) : null}
            {showLanguagePicker ? (
              <div className="search-printing-helper">
                <div className="search-language-picker">
                  <label htmlFor={languageFieldId}>Language</label>
                  <select
                    aria-label="Language"
                    className="text-input"
                    disabled={busy}
                    id={languageFieldId}
                    onChange={(event) => {
                      setSelectedLanguageCode(event.target.value);
                      setRecentlyAdded(false);
                    }}
                    value={selectedLanguageCode}
                  >
                    {availableLanguageCodes.map((languageCode) => (
                      <option key={languageCode} value={languageCode}>
                        {LANGUAGE_LABELS[languageCode] || formatLanguageCode(languageCode)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            ) : null}
          </div>

          {printingStatus === "loading" ? (
            <p className="field-hint field-hint-info">
              Loading printings for {props.group.name}...
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
                Retry loading printings
              </button>
            </div>
          ) : !hasLoadedExactPrintings ? (
            <p className="field-hint field-hint-info">
              Open the printing menu to see all available printings.
            </p>
          ) : null}

        </div>

        <div className="form-section form-section-muted">
          <div className="form-section-header">
            <strong>Optional details</strong>
            <span>{optionalDetailSummary}</span>
          </div>

          <label className="field">
            <span>Location</span>
            <input
              className="text-input"
              disabled={busy || !props.canAdd}
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
              disabled={busy || !props.canAdd}
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
              disabled={busy || !props.canAdd}
              onChange={(event) => {
                setNotes(event.target.value);
                setRecentlyAdded(false);
              }}
              placeholder="Add an optional note"
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
            Added. You can keep this card open and add another printing.
          </p>
        ) : null}
      </form>
    </article>
  );
}
