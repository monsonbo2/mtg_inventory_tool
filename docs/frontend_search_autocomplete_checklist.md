# Frontend Search Autocomplete Checklist

This checklist scopes a polished typeahead/autocomplete layer on top of the
existing demo search flow. It is meant to augment the current search-and-add
workflow, not replace the full result cards.

## Scope

- [ ] Keep the existing full search/results panel as the main workflow.
- [ ] Add autocomplete as a suggestion layer, not a replacement for the
  current result cards.
- [ ] Keep selection explicit: suggestion selection should run or fill the
  search flow, not auto-add a card.

## State

- [ ] Add dedicated suggestion state separate from the main search results.
- [ ] Track suggestion query, loading state, error state, open/closed state,
  and highlighted index.
- [ ] Add stale-request protection with a request-id ref or `AbortController`.
- [ ] Add small in-memory caching by query string for repeated lookups.

## Fetch Behavior

- [ ] Start suggesting only after at least 2 typed characters.
- [ ] Debounce requests by about 250ms.
- [ ] Query the existing `searchCards(...)` API with a small limit like 5.
- [ ] Keep `exact: false` so suggestions work as typeahead.
- [ ] Ignore stale responses if the input changes while a request is in flight.

## UI

- [ ] Add a dedicated autocomplete dropdown component under the search input.
- [ ] Show each suggestion with thumbnail, card name, set name or set code,
  and collector number.
- [ ] Add a lightweight loading state inside the dropdown.
- [ ] Add a "no suggestions" state when the query is valid but nothing matches.
- [ ] Keep the dropdown visually tied to the current search field and search
  panel styling.

## Interaction

- [ ] Open the dropdown when the query is valid and suggestion results exist.
- [ ] Close the dropdown on `Escape`.
- [ ] Close the dropdown on outside click.
- [ ] Reopen suggestions on refocus when the query is still valid.
- [ ] Support mouse hover and click selection.
- [ ] Support `ArrowDown` and `ArrowUp` to move the highlight.
- [ ] Support `Enter` to select the highlighted suggestion.
- [ ] Keep non-highlighted `Enter` behavior sane for normal search submission.

## Selection Behavior

- [ ] On suggestion select, populate the search input with the chosen card
  name.
- [ ] Immediately run the existing search flow so the main result panel
  updates.
- [ ] Clear or close the suggestion dropdown after selection.
- [ ] Preserve the current add-card flow exactly as it works now.

## Accessibility

- [ ] Use combobox/listbox semantics for the input and dropdown.
- [ ] Mark the active suggestion with the correct ARIA relationship.
- [ ] Ensure keyboard-only use works end to end.
- [ ] Make the highlighted item visually obvious.
- [ ] Ensure screen-reader labels are meaningful and not redundant.

## Tests

- [ ] Add tests for debounce behavior.
- [ ] Add tests for stale-response protection.
- [ ] Add tests for keyboard navigation.
- [ ] Add tests for `Enter` selection.
- [ ] Add tests for `Escape` close behavior.
- [ ] Add tests for outside-click close behavior.
- [ ] Add tests that selection syncs into the main search/result flow.

## Definition Of Done

- [ ] Typing into the search field shows stable suggestions quickly without
  spamming requests.
- [ ] Keyboard and mouse selection both work reliably.
- [ ] Suggestion state does not interfere with the existing main search
  results panel.
- [ ] `npm test -- --run` passes in `frontend/`.
- [ ] `npm run build` passes in `frontend/`.
