"""Inventory write-operation facade kept stable for callers."""

from .operations.add import add_card, add_card_with_connection
from .operations.bulk import bulk_mutate_inventory_items
from .operations.identity import (
    set_condition,
    set_location,
    set_printing,
    set_printing_with_connection,
)
from .operations.item_updates import (
    set_acquisition,
    set_finish,
    set_finish_with_connection,
    set_notes,
    set_quantity,
    set_tags,
)
from .operations.row_lifecycle import merge_rows, remove_card, split_row
