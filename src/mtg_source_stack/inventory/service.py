"""Public inventory domain facade used by the CLI and future app layer."""

from .access import (
    actor_can_read_any_inventory,
    actor_can_read_inventory,
    actor_can_write_inventory,
    actor_inventory_role,
    actor_inventory_role_with_connection,
    can_read_inventory,
    can_write_inventory,
    grant_inventory_membership,
    grant_inventory_membership_with_connection,
    is_global_admin,
    list_inventory_memberships,
    normalize_inventory_membership_role,
    revoke_inventory_membership,
)
from .audit import list_inventory_audit_events
from .analysis import (
    build_duplicate_groups_from_owned_rows,
    export_inventory_csv,
    inventory_health,
    inventory_report,
    list_owned,
    list_owned_filtered,
    list_price_gaps,
    reconcile_prices,
    render_inventory_csv_export,
    valuation,
    valuation_filtered,
)
from .catalog import (
    list_card_printings_for_oracle,
    resolve_card_row,
    search_card_names,
    search_cards,
    summarize_card_printings_for_oracle,
)
from .csv_import import import_csv, import_csv_stream
from .decklist_import import import_decklist_text
from .deck_url_import import import_deck_url
from .inventories import create_inventory, ensure_default_inventory, list_inventories, list_visible_inventories
from .inventories import summarize_actor_access
from .mutations import (
    add_card,
    add_card_with_connection,
    bulk_mutate_inventory_items,
    merge_rows,
    remove_card,
    set_acquisition,
    set_condition,
    set_finish,
    set_finish_with_connection,
    set_location,
    set_notes,
    set_printing,
    set_quantity,
    set_tags,
    split_row,
)
from .transfer import duplicate_inventory, transfer_inventory_items
