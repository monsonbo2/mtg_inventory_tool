import { useEffect, useId, useState } from "react";
import type { FormEvent, RefObject } from "react";

import type {
  AddInventoryItemRequest,
  CatalogPrintingLookupRow,
  FinishValue,
} from "../types";
import type { SearchCardGroup } from "../searchResultHelpers";
import type { AsyncStatus, NoticeTone, SearchAddAvailability } from "../uiTypes";
import {
  formatPrintingOptionLabel,
} from "../searchResultHelpers";
import {
  FINISH_OPTIONS,
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

type PrintingLoadMode = "primary" | "all";

function sortLanguageCodes(languageCodes: string[]) {
  return [...languageCodes].sort((left, right) => {
    if (left === "en") {
      return -1;
    }
    if (right === "en") {
      return 1;
    }
    return left.localeCompare(right);
  });
}

function formatPrintingDetail(printing: CatalogPrintingLookupRow) {
  return `${printing.set_code.toUpperCase()} #${printing.collector_number} · ${printing.set_name} · ${printing.lang.toUpperCase()}`;
}

export function SearchResultCard(props: {
  group: SearchCardGroup;
  busyPrintingId: string | null;
  addAvailability: SearchAddAvailability;
  autoLoadAllLanguages?: boolean;
  defaultLocation: string | null;
  defaultTags: string | null;
  onClose: () => void;
  quickAddSectionRef?: RefObject<HTMLDivElement | null>;
  onLoadPrintings: (
    group: SearchCardGroup,
    options?: { includeAllLanguages?: boolean },
  ) => Promise<CatalogPrintingLookupRow[]>;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  const [printings, setPrintings] = useState<CatalogPrintingLookupRow[]>([]);
  const [printingStatus, setPrintingStatus] = useState<AsyncStatus>("idle");
  const [printingError, setPrintingError] = useState<string | null>(null);
  const [loadedPrintingsMode, setLoadedPrintingsMode] = useState<
    PrintingLoadMode | null
  >(null);
  const [printingLoadMode, setPrintingLoadMode] = useState<PrintingLoadMode | null>(
    null,
  );
  const [selectedPrintingId, setSelectedPrintingId] = useState("");
  const [showLanguagePicker, setShowLanguagePicker] = useState(false);
  const [showNotesField, setShowNotesField] = useState(false);
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
    setLoadedPrintingsMode(null);
    setPrintingLoadMode(null);
    setSelectedPrintingId("");
    setShowLanguagePicker(false);
    setShowNotesField(false);
    setSelectedLanguageCode("en");
    setQuantity("1");
    setFinish("normal");
    setLocation("");
    setNotes("");
    setTags("");
    setRecentlyAdded(false);
  }, [props.group.groupId]);

  useEffect(() => {
    if (loadedPrintingsMode !== null || printingStatus !== "idle") {
      return;
    }

    void loadPrintings(props.autoLoadAllLanguages ? "all" : "primary");
  }, [
    loadedPrintingsMode,
    printingStatus,
    props.autoLoadAllLanguages,
    props.group.groupId,
  ]);

  const activePrinting =
    printings.find((printing) => printing.scryfall_id === selectedPrintingId) || null;
  const defaultPrinting =
    printings.find((printing) => printing.is_default_add_choice) || null;
  const effectivePrinting = activePrinting || defaultPrinting;
  const busy =
    props.busyPrintingId !== null &&
    props.busyPrintingId === effectivePrinting?.scryfall_id;
  const availableLanguageCodes = sortLanguageCodes(
    Array.from(new Set(printings.map((printing) => printing.lang))),
  );
  const allAvailableLanguageCodes = sortLanguageCodes(
    props.group.availableLanguages.length
      ? props.group.availableLanguages
      : availableLanguageCodes,
  );
  const hasEnglishPrintings = availableLanguageCodes.includes("en");
  const hasLoadedPrimaryPrintings = loadedPrintingsMode !== null;
  const hasLoadedAllPrintings = loadedPrintingsMode === "all";
  const hasAdditionalLanguages = allAvailableLanguageCodes.some(
    (languageCode) => !availableLanguageCodes.includes(languageCode),
  );
  const isLoadingInitialPrintings =
    printingStatus === "loading" && printingLoadMode !== "all";
  const isLoadingAllLanguages =
    printingStatus === "loading" && printingLoadMode === "all";
  const visiblePrintings = showLanguagePicker
    ? printings.filter((printing) => printing.lang === selectedLanguageCode)
    : hasEnglishPrintings
      ? printings.filter((printing) => printing.lang === "en")
      : printings;

  useEffect(() => {
    if (!props.autoLoadAllLanguages) {
      return;
    }
    if (loadedPrintingsMode !== "primary" || printingStatus === "loading") {
      return;
    }
    if (!hasAdditionalLanguages) {
      return;
    }

    void loadPrintings("all");
  }, [
    hasAdditionalLanguages,
    loadedPrintingsMode,
    printingStatus,
    props.autoLoadAllLanguages,
  ]);

  useEffect(() => {
    if (!effectivePrinting) {
      setFinish("normal");
      return;
    }

    if (!effectivePrinting.finishes.includes(finish)) {
      setFinish(effectivePrinting.finishes[0] || "normal");
      setRecentlyAdded(false);
    }
  }, [effectivePrinting, finish]);

  useEffect(() => {
    if (!availableLanguageCodes.length) {
      setSelectedLanguageCode("en");
      return;
    }

    setSelectedLanguageCode((current) => {
      if (
        availableLanguageCodes.includes(
          current as (typeof availableLanguageCodes)[number],
        )
      ) {
        return current;
      }
      return hasEnglishPrintings ? "en" : availableLanguageCodes[0];
    });
  }, [availableLanguageCodes, hasEnglishPrintings]);

  useEffect(() => {
    if (!selectedPrintingId) {
      return;
    }

    if (
      !visiblePrintings.some((printing) => printing.scryfall_id === selectedPrintingId)
    ) {
      setSelectedPrintingId("");
    }
  }, [selectedPrintingId, visiblePrintings]);

  const parsedQuantity = Number.parseInt(quantity, 10);
  const parsedTags = parseTags(tags);
  const trimmedLocation = location.trim();
  const trimmedNotes = notes.trim();
  const fallbackLocation = props.defaultLocation?.trim() || "";
  const fallbackTags = parseTags(props.defaultTags || "");
  const effectiveLocation = trimmedLocation || fallbackLocation;
  const effectiveTags = parsedTags.length
    ? Array.from(new Set([...fallbackTags, ...parsedTags]))
    : fallbackTags;
  const quantityIsValid = Number.isInteger(parsedQuantity) && parsedQuantity > 0;
  const notesVisible = showNotesField || Boolean(trimmedNotes);
  const canAdd = props.addAvailability === "writable";
  const needsPrintingSelection = canAdd && !effectivePrinting;
  const printingsAvailableLabel = `${props.group.printingsCount} printing${
    props.group.printingsCount === 1 ? "" : "s"
  } available`;
  const addBlockedLabel =
    props.addAvailability === "read_only" ? "Read-only collection" : "Select collection";
  const addButtonLabel = busy
    ? "Adding..."
    : recentlyAdded
      ? "Added"
      : !canAdd
        ? addBlockedLabel
        : isLoadingInitialPrintings && !effectivePrinting
          ? "Loading printings..."
          : needsPrintingSelection
            ? "Select printing first"
            : quantityIsValid
              ? "Add to collection"
              : "Enter valid qty";
  const availableFinishes = FINISH_OPTIONS.filter((option) =>
    effectivePrinting?.finishes.includes(option.value),
  );
  const resolvedFinish =
    effectivePrinting && !effectivePrinting.finishes.includes(finish)
      ? effectivePrinting.finishes[0] || "normal"
      : finish;
  const effectivePrintingDetail = effectivePrinting
    ? formatPrintingDetail(effectivePrinting)
    : null;
  const headerPrintingModeLabel = activePrinting
    ? "Selected printing"
    : defaultPrinting
      ? "Using default printing"
      : isLoadingInitialPrintings
        ? "Loading printings"
        : needsPrintingSelection
          ? "Printing required"
          : "Printings";
  const headerPrintingDetail = effectivePrintingDetail ?? printingsAvailableLabel;
  const addStatusTone =
    !canAdd || !quantityIsValid || printingStatus === "error"
      ? "error"
      : recentlyAdded
        ? "success"
        : busy || isLoadingInitialPrintings || isLoadingAllLanguages
          ? "info"
          : "ready";
  const addStatusMessage = !canAdd
    ? props.addAvailability === "read_only"
      ? "This collection is read-only. Choose a writable collection before adding cards."
      : "Choose a collection before adding cards."
    : !quantityIsValid
      ? "Enter a whole-number quantity greater than 0."
      : busy
        ? "Adding this printing to the selected collection."
        : recentlyAdded
          ? "Added. You can add another printing from this card."
          : isLoadingInitialPrintings && !effectivePrinting
            ? "Loading the quickest add-ready printings."
            : printingStatus === "error"
              ? "Printing choices could not load."
              : needsPrintingSelection
                ? "Choose a printing before adding this card."
                : activePrinting
                  ? "Ready to add the selected printing."
                  : defaultPrinting
                  ? "Ready to add the backend default printing."
                    : "Ready.";
  const showAddStatus = recentlyAdded || !canAdd || !quantityIsValid;
  const supportMessage = showAddStatus
    ? addStatusMessage
    : isLoadingInitialPrintings
      ? `Loading add-ready printings for ${props.group.name}...`
      : isLoadingAllLanguages
        ? `Loading all available languages for ${props.group.name}...`
        : printingStatus === "error"
          ? printingError || "Could not load printings for this card."
          : hasLoadedAllPrintings && showLanguagePicker
            ? "All available languages are loaded."
            : !activePrinting && !defaultPrinting && hasLoadedPrimaryPrintings
              ? "Choose a printing to finish adding this card."
              : null;
  const tagPlaceholder = props.defaultTags?.trim() || "burn, trade";

  async function loadPrintings(mode: PrintingLoadMode) {
    if (
      printingStatus === "loading" &&
      printingLoadMode === mode
    ) {
      return null;
    }

    if (mode === "primary" && loadedPrintingsMode !== null) {
      return (
        printings.find((printing) => printing.scryfall_id === selectedPrintingId) ||
        printings.find((printing) => printing.is_default_add_choice) ||
        null
      );
    }

    if (mode === "all" && loadedPrintingsMode === "all") {
      return (
        printings.find((printing) => printing.scryfall_id === selectedPrintingId) ||
        printings.find((printing) => printing.is_default_add_choice) ||
        null
      );
    }

    setPrintingStatus("loading");
    setPrintingLoadMode(mode);
    setPrintingError(null);

    try {
      const nextPrintings = await props.onLoadPrintings(props.group, {
        includeAllLanguages: mode === "all",
      });
      const nextSelectedPrinting =
        nextPrintings.find((printing) => printing.scryfall_id === selectedPrintingId) ||
        null;
      const nextDefaultPrinting =
        nextPrintings.find((printing) => printing.is_default_add_choice) || null;
      const nextResolvedPrinting = nextSelectedPrinting || nextDefaultPrinting;
      const preferredLanguageCode =
        nextSelectedPrinting?.lang ||
        nextResolvedPrinting?.lang ||
        nextPrintings[0]?.lang ||
        "en";

      setPrintings(nextPrintings);
      setSelectedPrintingId(nextSelectedPrinting?.scryfall_id || "");
      setSelectedLanguageCode(preferredLanguageCode);
      setShowLanguagePicker(
        mode === "all" &&
          new Set(nextPrintings.map((printing) => printing.lang)).size > 1,
      );
      setLoadedPrintingsMode(mode === "all" ? "all" : "primary");
      setPrintingStatus("ready");
      setPrintingLoadMode(null);
      return nextResolvedPrinting;
    } catch (error) {
      setPrintingStatus("error");
      setPrintingLoadMode(null);
      setPrintingError(toUserMessage(error, "Could not load printings for this card."));
      return null;
    }
  }

  function ensurePrimaryPrintingsLoaded() {
    if (!hasLoadedPrimaryPrintings) {
      void loadPrintings("primary");
    }
  }

  async function handleLoadAllLanguages() {
    const nextResolvedPrinting = await loadPrintings("all");
    if (nextResolvedPrinting) {
      setSelectedLanguageCode(nextResolvedPrinting.lang);
      setShowLanguagePicker(true);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!canAdd) {
      props.onNotice(
        props.addAvailability === "read_only"
          ? "This collection is read-only. Choose a writable collection before adding a card."
          : "Select a collection before adding a card.",
        "error",
      );
      return;
    }

    const resolvedPrinting =
      effectivePrinting || (!hasLoadedPrimaryPrintings ? await loadPrintings("primary") : null);

    if (!resolvedPrinting) {
      props.onNotice("Choose a printing before adding this card.", "error");
      return;
    }

    if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) {
      props.onNotice("Enter a whole-number quantity greater than 0.", "error");
      return;
    }

    const didAdd = await props.onAdd({
      scryfall_id: resolvedPrinting.scryfall_id,
      quantity: parsedQuantity,
      finish: resolvedFinish,
      location: effectiveLocation || undefined,
      notes: trimmedNotes || null,
      tags: effectiveTags.length ? effectiveTags : undefined,
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
            imageUrl={effectivePrinting?.image_uri_small || props.group.image_uri_small}
            imageUrlLarge={effectivePrinting?.image_uri_normal || props.group.image_uri_normal}
            name={props.group.name}
            variant="search"
          />

          <div className="card-hero-body">
            <div className="result-card-header search-result-titlebar">
              <div className="search-result-title-copy">
                <h3>{props.group.name}</h3>
                <div aria-live="polite" className="search-result-title-meta">
                  <span
                    className={
                      activePrinting
                        ? "search-printing-mode-pill search-printing-mode-selected"
                        : defaultPrinting
                          ? "search-printing-mode-pill search-printing-mode-default"
                          : "search-printing-mode-pill"
                    }
                  >
                    {headerPrintingModeLabel}
                  </span>
                  <span className="search-result-title-detail">{headerPrintingDetail}</span>
                </div>
              </div>
              <button
                aria-label="Close add card pane"
                className="search-result-close"
                onClick={props.onClose}
                type="button"
              >
                ×
              </button>
            </div>
          </div>
        </div>

        <div className="form-section search-result-form-shell" ref={props.quickAddSectionRef}>
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
                onFocus={ensurePrimaryPrintingsLoaded}
                value={selectedPrintingId}
              >
                <option value="">{printingsAvailableLabel}</option>
                {visiblePrintings.map((printing) => (
                  <option key={printing.scryfall_id} value={printing.scryfall_id}>
                    {formatPrintingOptionLabel(printing)}
                  </option>
                ))}
              </select>
            </div>

            <label className="field">
              <span>Qty</span>
              <input
                className="text-input"
                disabled={busy || !canAdd}
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
                  busy || !canAdd || !effectivePrinting || availableFinishes.length <= 1
                }
                onChange={(event) => {
                  setFinish(event.target.value as FinishValue);
                  setRecentlyAdded(false);
                }}
                value={resolvedFinish}
              >
                {!effectivePrinting ? <option value="normal">Choose printing first</option> : null}
                {availableFinishes.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <button
              className="primary-button search-result-add-button"
              disabled={
                busy ||
                !canAdd ||
                !quantityIsValid ||
                (isLoadingInitialPrintings && !effectivePrinting) ||
                (hasLoadedPrimaryPrintings && !effectivePrinting)
              }
              type="submit"
            >
              {addButtonLabel}
            </button>
          </div>

          <div className="search-result-support-strip">
            <div className="search-result-support-copy">
              {supportMessage ? (
                <p
                  aria-live="polite"
                  className={`field-hint ${
                    addStatusTone === "error" || printingStatus === "error"
                      ? "field-hint-error"
                      : addStatusTone === "success"
                        ? "field-hint-success"
                        : "field-hint-info"
                  } search-result-support-message`}
                >
                  {supportMessage}
                </p>
              ) : null}
            </div>

            <div className="search-result-support-actions">
              {showLanguagePicker ? (
                <div className="search-language-picker-inline">
                  <label htmlFor={languageFieldId}>Language</label>
                  <select
                    aria-label="Language"
                    className="text-input"
                    disabled={busy || isLoadingAllLanguages}
                    id={languageFieldId}
                    onChange={(event) => {
                      setSelectedLanguageCode(event.target.value);
                      setRecentlyAdded(false);
                    }}
                    value={selectedLanguageCode}
                  >
                    {allAvailableLanguageCodes.map((languageCode) => (
                      <option key={languageCode} value={languageCode}>
                        {LANGUAGE_LABELS[languageCode] || formatLanguageCode(languageCode)}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}

              {hasAdditionalLanguages && !hasLoadedAllPrintings ? (
                <button
                  className="secondary-button search-printing-expander-button"
                  disabled={isLoadingAllLanguages}
                  onClick={() => {
                    void handleLoadAllLanguages();
                    setRecentlyAdded(false);
                  }}
                  type="button"
                >
                  {isLoadingAllLanguages ? "Loading all languages..." : "Load all languages"}
                </button>
              ) : null}

              {printingStatus === "error" ? (
                <button
                  className="secondary-button search-printing-expander-button"
                  onClick={() => {
                    void loadPrintings(hasLoadedPrimaryPrintings ? "all" : "primary");
                  }}
                  type="button"
                >
                  Retry loading printings
                </button>
              ) : null}

              <button
                className="field-link-button search-result-note-toggle"
                onClick={() => {
                  setShowNotesField((current) => {
                    if (current && trimmedNotes) {
                      return true;
                    }
                    return !current;
                  });
                  setRecentlyAdded(false);
                }}
                type="button"
              >
                {notesVisible ? "Hide note" : "Add note"}
              </button>
            </div>
          </div>

          <div className="search-result-details-grid">
            <label className="field">
              <span>Location</span>
              <input
                className="text-input"
                disabled={busy || !canAdd}
                onChange={(event) => {
                  setLocation(event.target.value);
                  setRecentlyAdded(false);
                }}
                placeholder={fallbackLocation || "Red Binder"}
                value={location}
              />
            </label>

            <label className="field">
              <span>Tags</span>
              <input
                className="text-input"
                disabled={busy || !canAdd}
                onChange={(event) => {
                  setTags(event.target.value);
                  setRecentlyAdded(false);
                }}
                placeholder={tagPlaceholder}
                value={tags}
              />
            </label>

            {notesVisible ? (
              <label className="field search-result-notes-field">
                <span>Notes</span>
                <textarea
                  className="text-area"
                  disabled={busy || !canAdd}
                  onChange={(event) => {
                    setNotes(event.target.value);
                    setRecentlyAdded(false);
                  }}
                  placeholder="Add an optional note"
                  rows={2}
                  value={notes}
                />
              </label>
            ) : null}
          </div>
        </div>

        {!quantityIsValid ? (
          <p className="field-hint field-hint-error">
            Enter a whole-number quantity greater than 0.
          </p>
        ) : null}
      </form>
    </article>
  );
}
