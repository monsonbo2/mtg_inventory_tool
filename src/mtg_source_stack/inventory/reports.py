"""Compatibility facade for inventory reporting helpers."""

from .report_formatters import (
    append_snapshot_notice,
    format_add_card_result,
    format_export_csv_result,
    format_import_csv_result,
    format_inventory_health_result,
    format_inventory_report_result,
    format_merge_rows_result,
    format_owned_rows,
    format_price_gap_rows,
    format_reconcile_prices_result,
    format_remove_card_result,
    format_set_acquisition_result,
    format_set_condition_result,
    format_set_finish_result,
    format_set_location_result,
    format_set_notes_result,
    format_set_quantity_result,
    format_set_tags_result,
    format_split_row_result,
)
from .report_helpers import (
    append_preview_section,
    build_currency_totals,
    build_top_value_rows,
    print_table,
    render_table,
    summarize_filters,
)
from .report_io import (
    EXPORT_CSV_FIELDNAMES,
    flatten_import_csv_rows,
    flatten_owned_export_rows,
    write_csv_report,
    write_inventory_export_csv,
    write_json_report,
    write_report,
    write_rows_csv,
)
