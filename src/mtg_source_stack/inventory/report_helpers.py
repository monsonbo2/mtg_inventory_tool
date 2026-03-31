from __future__ import annotations

from typing import Any

from .normalize import coerce_float, parse_tag_filters, text_or_none, truncate


def render_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "No rows found."

    widths: list[int] = []
    for key, label in columns:
        width = len(label)
        for row in rows:
            width = max(width, len(str(row.get(key, ""))))
        widths.append(width)

    header = "  ".join(label.ljust(width) for (_, label), width in zip(columns, widths))
    separator = "  ".join("-" * width for width in widths)
    lines = [header, separator]
    for row in rows:
        line = "  ".join(str(row.get(key, "")).ljust(width) for (key, _), width in zip(columns, widths))
        lines.append(line)
    return "\n".join(lines)


def print_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
    print(render_table(rows, columns))


def summarize_filters(
    *,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
) -> str:
    filters: list[str] = []
    if query:
        filters.append(f"query={query}")
    if set_code:
        filters.append(f"set={set_code}")
    if rarity:
        filters.append(f"rarity={rarity}")
    if finish:
        filters.append(f"finish={finish}")
    if condition_code:
        filters.append(f"condition={condition_code}")
    if language_code:
        filters.append(f"language={language_code}")
    if location:
        filters.append(f"location~={location}")
    normalized_tags = parse_tag_filters(tags)
    if normalized_tags:
        filters.append(f"tags={', '.join(normalized_tags)}")
    return ", ".join(filters) if filters else "(none)"


def build_currency_totals(
    rows: list[dict[str, Any]],
    *,
    value_key: str,
    currency_key: str,
    quantity_key: str,
) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        amount = coerce_float(row.get(value_key))
        currency = text_or_none(row.get(currency_key))
        if amount is None or currency is None:
            continue
        bucket = totals.setdefault(
            currency,
            {"currency": currency, "item_rows": 0, "total_cards": 0, "total_amount": 0.0},
        )
        bucket["item_rows"] += 1
        bucket["total_cards"] += int(row.get(quantity_key, 0) or 0)
        if value_key == "acquisition_price":
            bucket["total_amount"] += amount * int(row.get(quantity_key, 0) or 0)
        else:
            bucket["total_amount"] += amount
    formatted: list[dict[str, Any]] = []
    for currency, bucket in sorted(totals.items()):
        formatted.append(
            {
                "currency": currency,
                "item_rows": bucket["item_rows"],
                "total_cards": bucket["total_cards"],
                "total_amount": round(bucket["total_amount"], 2),
            }
        )
    return formatted


def build_top_value_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: (coerce_float(row.get("est_value")) or 0.0, int(row.get("quantity", 0) or 0)),
        reverse=True,
    )
    top_rows: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        top_rows.append(
            {
                "item_id": row["item_id"],
                "name": truncate(row["name"], 28),
                "set": row["set_code"],
                "number": row["collector_number"],
                "qty": row["quantity"],
                "finish": row["finish"],
                "location": truncate(text_or_none(row["location"]) or "(none)", 18),
                "est_value": row["est_value"],
                "currency": row["currency"],
            }
        )
    return top_rows


def append_preview_section(
    lines: list[str],
    *,
    title: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    overflow_label: str,
    limit: int,
) -> None:
    if not rows:
        return

    preview_rows = rows[:limit]
    lines.extend(["", title, "", render_table(preview_rows, columns)])
    remaining = len(rows) - len(preview_rows)
    if remaining > 0:
        lines.append(f"... {remaining} more {overflow_label} not shown.")
