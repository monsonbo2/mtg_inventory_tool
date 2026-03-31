"""Compatibility facade for inventory query helpers."""

from .query_catalog import add_catalog_filters, build_catalog_finish_filter
from .query_inventory import (
    add_owned_filters,
    find_inventory_item_collision,
    get_inventory_item_row,
    get_inventory_row,
    get_or_create_inventory_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
)
from .query_pricing import (
    build_current_retail_prices_cte,
    build_latest_retail_prices_cte,
    build_price_gap_result,
    query_price_gaps,
    query_stale_price_rows,
)
from .query_reporting import (
    build_health_item_preview,
    query_duplicate_like_groups,
    query_inventory_summary,
    query_merge_note_rows,
    query_missing_location_rows,
    query_missing_tag_rows,
)
from .policies import resolve_merge_acquisition
