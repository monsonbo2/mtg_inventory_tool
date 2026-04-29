"""Compatibility facade for catalog lookups and resolution."""

from __future__ import annotations

from .catalog_printings import (
    _rank_oracle_default_printing_rows,
    list_card_printings_for_oracle,
    summarize_card_printings_for_oracle,
)
from .catalog_resolution import (
    _candidate_rows_text,
    _catalog_resolution_rows,
    _rows_matching_finish,
    determine_printing_selection_mode,
    list_default_card_name_candidate_rows,
    list_printing_candidate_rows,
    list_tcgplayer_product_candidate_rows,
    resolve_card_row,
    resolve_default_card_row_for_name,
)
from .catalog_search import search_card_names, search_cards

