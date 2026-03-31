"""Public inventory domain facade used by the CLI and future app layer."""

from .analysis import (
    build_duplicate_groups_from_owned_rows,
    export_inventory_csv,
    inventory_health,
    inventory_report,
    list_owned,
    list_owned_filtered,
    list_price_gaps,
    reconcile_prices,
    valuation,
    valuation_filtered,
)
from .catalog import resolve_card_row, search_cards
from .inventories import create_inventory, list_inventories
from .mutations import (
    add_card,
    add_card_with_connection,
    merge_rows,
    remove_card,
    set_acquisition,
    set_condition,
    set_finish,
    set_finish_with_connection,
    set_location,
    set_notes,
    set_quantity,
    set_tags,
    split_row,
)
