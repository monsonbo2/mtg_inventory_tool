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

export function SearchResultCard(props: {
  group: SearchCardGroup;
  busyPrintingId: string | null;
  canAdd: boolean;
  defaultLocation: string | null;
  defaultTags: string | null;
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

    void loadPrintings("primary");
  }, [loadedPrintingsMode, printingStatus, props.group.groupId]);

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
  const optionalDetailSummary =
    [
      effectiveLocation ? `Location: ${effectiveLocation}` : null,
      effectiveTags.length
        ? `${effectiveTags.length} tag${effectiveTags.length === 1 ? "" : "s"}`
        : null,
      trimmedNotes ? "Note ready" : null,
    ].filter(Boolean).join(" · ") || "No optional details yet";
  const needsPrintingSelection = props.canAdd && !effectivePrinting;
  const printingsAvailableLabel = `${props.group.printingsCount} printing${
    props.group.printingsCount === 1 ? "" : "s"
  } available`;
  const addButtonLabel = busy
    ? "Adding..."
    : recentlyAdded
      ? "Added"
      : !props.canAdd
        ? "Select collection"
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
  const selectedPrintingSummary = activePrinting
    ? `${activePrinting.set_name} · #${activePrinting.collector_number} · ${activePrinting.lang.toUpperCase()}${
        activePrinting.is_default_add_choice ? " · Default add choice" : ""
      }`
    : isLoadingAllLanguages
      ? "Loading all available printings for this card."
      : isLoadingInitialPrintings
        ? "Loading quick-add printings for this card."
        : defaultPrinting
          ? "Ready to add with the default printing, or choose another printing below."
          : hasLoadedPrimaryPrintings
            ? "Choose a printing below to add this card."
            : "Loading quick-add printings for this card.";

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

    if (!props.canAdd) {
      props.onNotice("Select a collection before adding a card.");
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
              disabled={
                busy ||
                !props.canAdd ||
                !quantityIsValid ||
                (isLoadingInitialPrintings && !effectivePrinting) ||
                (hasLoadedPrimaryPrintings && !effectivePrinting)
              }
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
                onFocus={ensurePrimaryPrintingsLoaded}
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
                  busy || !props.canAdd || !effectivePrinting || availableFinishes.length <= 1
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

            {hasAdditionalLanguages && !hasLoadedAllPrintings ? (
              <div className="search-printing-helper">
                <button
                  className="field-link-button"
                  disabled={isLoadingAllLanguages}
                  onClick={() => {
                    void handleLoadAllLanguages();
                    setRecentlyAdded(false);
                  }}
                  type="button"
                >
                  {isLoadingAllLanguages ? "Loading all languages..." : "Load all languages"}
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
              </div>
            ) : null}
          </div>

          {isLoadingInitialPrintings ? (
            <p className="field-hint field-hint-info">
              Loading quick-add printings for {props.group.name}...
            </p>
          ) : isLoadingAllLanguages ? (
            <p className="field-hint field-hint-info">
              Loading all available languages for {props.group.name}...
            </p>
          ) : printingStatus === "error" ? (
            <div className="search-printing-state">
              <p className="field-hint field-hint-error">
                {printingError || "Could not load printings for this card."}
              </p>
              <button
                className="secondary-button"
                onClick={() => {
                  void loadPrintings(hasLoadedPrimaryPrintings ? "all" : "primary");
                }}
                type="button"
              >
                Retry loading printings
              </button>
            </div>
          ) : !activePrinting && !defaultPrinting && hasLoadedPrimaryPrintings ? (
            <p className="field-hint field-hint-info">
              Choose a printing to finish adding this card.
            </p>
          ) : hasAdditionalLanguages && !hasLoadedAllPrintings ? (
            <p className="field-hint field-hint-info">
              Showing add-ready printings first. Load all languages to browse every
              available printing for this card.
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
