import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

import type {
  FinishValue,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
} from "../types";
import type { ItemMutationAction, MutationOutcome } from "../uiTypes";
import {
  decimalToNumber,
  equalStringArrays,
  formatFinishLabel,
  formatUsd,
  getAvailableFinishesForOwnedRow,
  getBusyMessage,
  getInventoryLocationSuggestions,
  getTagChipStyle,
  normalizeOptionalText,
  parseTags,
} from "../uiHelpers";
import { CardThumbnail } from "./ui/CardThumbnail";

export function CompactInventoryList(props: {
  items: OwnedInventoryRow[];
  busyItem: { itemId: number; action: ItemMutationAction } | null;
  onOpenDetails: (itemId: number) => void;
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<MutationOutcome>;
}) {
  const locationSuggestionsId = useId();
  const locationSuggestions = getInventoryLocationSuggestions(props.items);

  return (
    <div className="compact-collection-list">
      {locationSuggestions.length ? (
        <datalist id={locationSuggestionsId}>
          {locationSuggestions.map((location) => (
            <option key={location} value={location} />
          ))}
        </datalist>
      ) : null}
      {props.items.map((item) => (
        <CompactInventoryRow
          busyAction={props.busyItem?.itemId === item.item_id ? props.busyItem.action : null}
          item={item}
          key={item.item_id}
          locationSuggestionsId={locationSuggestions.length ? locationSuggestionsId : undefined}
          onOpenDetails={props.onOpenDetails}
          onPatch={props.onPatch}
        />
      ))}
    </div>
  );
}

function CompactInventoryRow(props: {
  item: OwnedInventoryRow;
  busyAction: ItemMutationAction | null;
  locationSuggestionsId?: string;
  onOpenDetails: (itemId: number) => void;
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<MutationOutcome>;
}) {
  const [quantity, setQuantity] = useState(String(props.item.quantity));
  const [finish, setFinish] = useState<FinishValue>(props.item.finish);
  const [location, setLocation] = useState(props.item.location || "");
  const [tags, setTags] = useState<string[]>(props.item.tags);
  const [tagDraft, setTagDraft] = useState("");
  const [tagsActive, setTagsActive] = useState(false);
  const [removingTag, setRemovingTag] = useState<string | null>(null);
  const [tagFeedback, setTagFeedback] = useState<{ message: string; tone: "info" | "success" } | null>(null);
  const [savedField, setSavedField] = useState<ItemMutationAction | null>(null);
  const tagInputRef = useRef<HTMLInputElement | null>(null);
  const tagsFieldRef = useRef<HTMLDivElement | null>(null);
  const shouldRestoreTagFocusRef = useRef(false);
  const requestedRemovalTagRef = useRef<string | null>(null);

  useEffect(() => {
    setQuantity(String(props.item.quantity));
    setFinish(props.item.finish);
    setLocation(props.item.location || "");
    setTags(props.item.tags);
    setTagDraft("");
    setTagsActive(false);
    setRemovingTag(null);
    const removedTag = requestedRemovalTagRef.current;
    if (removedTag && !props.item.tags.includes(removedTag)) {
      setTagFeedback({ message: `Removed ${removedTag}.`, tone: "success" });
      requestedRemovalTagRef.current = null;
    }
  }, [props.item.finish, props.item.item_id, props.item.location, props.item.quantity, props.item.tags]);

  useEffect(() => {
    if (!tagFeedback) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setTagFeedback((current) => (current === tagFeedback ? null : current));
    }, 2000);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [tagFeedback]);

  useEffect(() => {
    if (!savedField) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setSavedField((current) => (current === savedField ? null : current));
    }, 1400);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [savedField]);

  useEffect(() => {
    if (!shouldRestoreTagFocusRef.current || props.busyAction === "tags") {
      return;
    }

    shouldRestoreTagFocusRef.current = false;
    window.requestAnimationFrame(() => {
      tagInputRef.current?.focus();
    });
  }, [props.busyAction]);

  function markFieldSaved(action: ItemMutationAction) {
    setSavedField(action);
  }

  function didMutationApply(outcome: MutationOutcome) {
    return outcome === "applied" || outcome === "applied_view_stale";
  }

  function deactivateTagsEditor() {
    setTagsActive(false);
    tagInputRef.current?.blur();
  }

  async function saveQuantity() {
    if (!quantityIsValid) {
      return;
    }
    const outcome = await props.onPatch(props.item.item_id, "quantity", {
      quantity: parsedQuantity,
    });
    if (didMutationApply(outcome)) {
      markFieldSaved("quantity");
    }
  }

  async function saveLocation() {
    const trimmed = location.trim();
    const outcome = await props.onPatch(
      props.item.item_id,
      "location",
      trimmed ? { location: trimmed } : { clear_location: true },
    );
    if (didMutationApply(outcome)) {
      markFieldSaved("location");
    }
  }

  async function saveTags(nextTags: string[]) {
    const outcome = await props.onPatch(
      props.item.item_id,
      "tags",
      nextTags.length ? { tags: nextTags } : { clear_tags: true },
    );
    if (didMutationApply(outcome)) {
      markFieldSaved("tags");
    }
    return outcome;
  }

  async function commitPendingTags() {
    const parsedDraftTags = parseTags(tagDraft);
    if (!parsedDraftTags.length) {
      return;
    }

    const nextTags = [...tags];
    let didAddTag = false;
    for (const tag of parsedDraftTags) {
      if (!nextTags.includes(tag)) {
        nextTags.push(tag);
        didAddTag = true;
      }
    }

    setTagFeedback(null);
    if (!didAddTag) {
      return;
    }

    shouldRestoreTagFocusRef.current = true;
    const outcome = await saveTags(nextTags);
    if (!didMutationApply(outcome)) {
      return;
    }

    setTagDraft("");
    setTags(nextTags);
  }

  async function removeTag(tagToRemove: string) {
    const nextTags = tags.filter((tag) => tag !== tagToRemove);
    shouldRestoreTagFocusRef.current = true;
    setRemovingTag(tagToRemove);
    setTagFeedback(null);
    const outcome = await saveTags(nextTags);
    setRemovingTag(null);
    if (!didMutationApply(outcome)) {
      return;
    }

    requestedRemovalTagRef.current = tagToRemove;
    setTags(nextTags);
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
  const pendingTagCount = parseTags(tagDraft).length;
  const tagsDirty = !equalStringArrays(tags, props.item.tags);
  const busyMessage = props.busyAction ? getBusyMessage(props.busyAction) : null;
  const availableFinishes = getAvailableFinishesForOwnedRow(
    props.item.finish,
    props.item.allowed_finishes,
  );
  const finishEditorLocked = availableFinishes.length <= 1;
  const statusMessage = busyMessage;
  const statusClassName = "row-status-label row-status-busy compact-row-status";
  const tagHint = pendingTagCount
    ? "Press Enter to add the tag."
    : removingTag
      ? `Removing ${removingTag}...`
      : tagFeedback
        ? tagFeedback.message
        : tagsActive && tags.length
          ? "Click a tag to remove it."
          : "";
  const tagHintClassName = `field-hint compact-row-tags-hint ${
    tagFeedback?.tone === "success" ? "field-hint-success" : "field-hint-info"
  }`;
  const tagsFieldHasExtraContent = tags.length > 0 || Boolean(tagHint);

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
            <div className="compact-row-heading">
              <h3>{props.item.name}</h3>
              <button
                className="field-link-button compact-row-detail-button"
                onClick={() => props.onOpenDetails(props.item.item_id)}
                type="button"
              >
                Open details
              </button>
              <p className="result-card-subtitle">
                {props.item.set_name} · #{props.item.collector_number}
              </p>
            </div>
            {statusMessage ? <p className={statusClassName}>{statusMessage}</p> : null}
          </div>
        </div>

        <div className="compact-row-fields">
          <InlineEditor
            dirty={quantityDirty}
            hint={quantityHasError ? "Enter a whole-number quantity greater than 0." : undefined}
            hintTone={quantityHasError ? "error" : undefined}
            invalid={quantityHasError}
            label="Quantity"
            saved={savedField === "quantity"}
          >
            <input
              className="text-input"
              disabled={isBusy}
              min="1"
              onBlur={() => {
                if (quantityDirty && quantityIsValid) {
                  void saveQuantity();
                }
              }}
              onChange={(event) => {
                setSavedField(null);
                setQuantity(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  event.currentTarget.blur();
                }
              }}
              type="number"
              value={quantity}
            />
          </InlineEditor>

          <InlineEditor dirty={finishDirty} label="Finish" saved={savedField === "finish"}>
            <select
              className="text-input"
              disabled={isBusy || finishEditorLocked}
              onChange={(event) => {
                const nextFinish = event.target.value as FinishValue;
                setSavedField(null);
                setFinish(nextFinish);
                const persistedFinish = props.item.finish;
                if (nextFinish !== persistedFinish) {
                  void (async () => {
                    const outcome = await props.onPatch(props.item.item_id, "finish", {
                      finish: nextFinish,
                    });
                    if (didMutationApply(outcome)) {
                      markFieldSaved("finish");
                      return;
                    }

                    setFinish(persistedFinish);
                  })();
                }
              }}
              value={finish}
            >
              {availableFinishes.map((value) => (
                <option key={value} value={value}>
                  {formatFinishLabel(value)}
                </option>
              ))}
            </select>
          </InlineEditor>

          <InlineEditor dirty={locationDirty} label="Location" saved={savedField === "location"}>
            <input
              className="text-input"
              disabled={isBusy}
              list={props.locationSuggestionsId}
              onBlur={() => {
                if (locationDirty) {
                  void saveLocation();
                }
              }}
              onChange={(event) => {
                setSavedField(null);
                setLocation(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  event.currentTarget.blur();
                }
              }}
              placeholder="Row location"
              value={location}
            />
          </InlineEditor>

          <InlineEditor dirty={tagsDirty} label="Tags" saved={savedField === "tags"}>
            <div
              className={[
                "compact-row-tags-editor",
                tagsActive ? "compact-row-tags-editor-active" : null,
                tagsFieldHasExtraContent
                  ? "compact-row-tags-editor-stacked"
                  : "compact-row-tags-editor-compact",
              ]
                .filter(Boolean)
                .join(" ")}
              onBlur={(event) => {
                if (!tagsFieldRef.current?.contains(event.relatedTarget as Node | null)) {
                  setTagsActive(false);
                }
              }}
              onMouseDown={(event) => {
                if (tagsActive) {
                  return;
                }

                if (event.target === tagInputRef.current) {
                  return;
                }

                event.preventDefault();
                setTagsActive(true);
                window.requestAnimationFrame(() => {
                  tagInputRef.current?.focus();
                });
              }}
              onFocus={() => setTagsActive(true)}
              ref={tagsFieldRef}
            >
              <input
                className="text-input"
                disabled={isBusy}
                ref={tagInputRef}
                onChange={(event) => {
                  setSavedField(null);
                  setTagDraft(event.target.value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    void commitPendingTags();
                    return;
                  }

                  if (
                    event.key === "Backspace" &&
                    !tagDraft &&
                    tags.length &&
                    !removingTag &&
                    !isBusy
                  ) {
                    event.preventDefault();
                    void removeTag(tags[tags.length - 1]);
                    return;
                  }

                  if (event.key === "Escape") {
                    event.preventDefault();
                    deactivateTagsEditor();
                  }
                }}
                placeholder="Add a tag"
                value={tagDraft}
              />
              {tagHint ? (
                <p aria-atomic="true" aria-live="polite" className={tagHintClassName}>
                  {tagHint}
                </p>
              ) : null}
              {tags.length ? (
                <div className="tag-row compact-row-field-tags">
                  {tags.map((tag) => (
                    tagsActive ? (
                      <button
                        aria-label={removingTag === tag ? `Removing tag ${tag}` : `Remove tag ${tag}`}
                        className={
                          removingTag === tag
                            ? "tag-chip compact-row-tag-chip compact-row-tag-chip-removable compact-row-tag-chip-busy"
                            : "tag-chip compact-row-tag-chip compact-row-tag-chip-removable"
                        }
                        disabled={isBusy}
                        key={tag}
                        onClick={() => {
                          if (removingTag) {
                            return;
                          }
                          void removeTag(tag);
                        }}
                        style={getTagChipStyle(tag)}
                        type="button"
                      >
                        <span>{tag}</span>
                        <span aria-hidden="true" className="compact-row-tag-remove-mark">
                          {removingTag === tag ? "…" : "×"}
                        </span>
                      </button>
                    ) : (
                      <span className="tag-chip compact-row-tag-chip" key={tag} style={getTagChipStyle(tag)}>
                        {tag}
                      </span>
                    )
                  ))}
                </div>
              ) : null}
            </div>
          </InlineEditor>

          <CompactStat
            label="Value"
            value={formatUsd(decimalToNumber(props.item.est_value))}
          />
        </div>
      </div>
    </article>
  );
}

function InlineEditor(props: {
  label: string;
  children: ReactNode;
  dirty?: boolean;
  invalid?: boolean;
  hint?: string;
  hintTone?: "info" | "error" | "success";
  saved?: boolean;
  wide?: boolean;
}) {
  const className = [
    "field",
    "inline-editor",
    props.dirty ? "inline-editor-dirty" : null,
    props.invalid ? "inline-editor-invalid" : null,
    props.saved ? "inline-editor-saved" : null,
    props.wide ? "wide" : null,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <label className={className}>
      <span className="inline-editor-header">
        <span className="inline-editor-label">{props.label}</span>
        <span
          aria-live="polite"
          className={props.saved ? "inline-editor-save-indicator inline-editor-save-indicator-visible" : "inline-editor-save-indicator"}
        >
          {props.saved ? "Saved" : ""}
        </span>
      </span>
      {props.children}
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
      <div className="compact-row-stat-header">
        <span className="compact-row-stat-label">{props.label}</span>
      </div>
      <strong className="compact-row-stat-value">{props.value}</strong>
    </div>
  );
}
