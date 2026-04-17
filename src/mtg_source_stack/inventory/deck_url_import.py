"""Remote deck URL import helpers."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
from html import unescape
import hmac
import json
import logging
from pathlib import Path
import socket
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
import re

from ..errors import MtgStackError, NotFoundError, ValidationError
from ..db.connection import connect
from ..db.schema import SchemaPreparationPolicy, prepare_database
from .catalog import (
    determine_printing_selection_mode,
    list_default_card_name_candidate_rows,
    list_printing_candidate_rows,
    resolve_card_row,
    resolve_default_card_row_for_name,
)
from .csv_import import InventoryValidator, PendingImportRow, _import_pending_rows
from .decklist_import import ParsedDecklistEntry, parse_decklist_text
from .import_resolution import (
    RemoteDeckRequestedCard,
    RemoteDeckResolutionIssue,
    RemoteDeckResolutionSelection,
    build_resolution_options_for_catalog_row,
)
from .import_summary import build_resolvable_deck_import_summary
from .normalize import DEFAULT_CONDITION_CODE, DEFAULT_FINISH, normalize_finish, text_or_none
from .query_inventory import get_inventory_row
from .response_models import serialize_response


_ARCHIDEKT_HOSTS = {"archidekt.com", "www.archidekt.com"}
_ARCHIDEKT_DECK_PATH_RE = re.compile(r"^/(?:api/)?decks/(?P<deck_id>\d+)(?:/.*)?$")
_AETHERHUB_HOSTS = {"aetherhub.com", "www.aetherhub.com"}
_AETHERHUB_DECK_PATH_RE = re.compile(r"^/(?:Metagame/[^/]+/)?Deck/(?P<deck_slug>[^/?#]+)(?:/.*)?$")
_MANABOX_HOSTS = {"manabox.app", "www.manabox.app"}
_MANABOX_DECK_PATH_RE = re.compile(r"^/decks/(?P<deck_id>[A-Za-z0-9_-]+)(?:/.*)?$")
_MOXFIELD_HOSTS = {"moxfield.com", "www.moxfield.com"}
_MOXFIELD_DECK_PATH_RE = re.compile(r"^/decks/(?P<public_id>[A-Za-z0-9_-]+)(?:/.*)?$")
_MTGGOLDFISH_HOSTS = {"mtggoldfish.com", "www.mtggoldfish.com"}
_MTGGOLDFISH_DECK_PATH_RE = re.compile(r"^/deck/(?P<deck_id>\d+)(?:[/-].*)?$")
_MTGGOLDFISH_ARENA_DOWNLOAD_PATH_RE = re.compile(r"^/deck/arena_download/(?P<deck_id>\d+)(?:/.*)?$")
_MTGGOLDFISH_DOWNLOAD_PATH_RE = re.compile(r"^/deck/download/(?P<deck_id>\d+)(?:/.*)?$")
_MTGTOP8_HOSTS = {"mtgtop8.com", "www.mtgtop8.com"}
_TAPPEDOUT_HOSTS = {"tappedout.net", "www.tappedout.net"}
_TAPPEDOUT_DECK_PATH_RE = re.compile(r"^/mtg-decks/(?P<deck_slug>[^/]+)(?:/.*)?$")
_MANABOX_MAIN_PROPS_RE = re.compile(
    r"<astro-island[^>]*component-export=['\"]Main['\"][^>]*props=['\"](?P<props>.*?)['\"]",
    re.IGNORECASE | re.DOTALL,
)
_MANABOX_BOARD_CATEGORY_TO_SECTION = {
    0: "commander",
    1: "companion",
    3: "mainboard",
    4: "sideboard",
    5: "attraction",
    6: "sticker",
}
_MANABOX_SKIPPED_BOARD_CATEGORIES = {2}
_MTGGOLDFISH_DOWNLOAD_ID_RE = re.compile(r'href="/deck/download/(?P<deck_id>\d+)')
_MTGGOLDFISH_TEXTAREA_RE = re.compile(
    r"<textarea[^>]*class=['\"]copy-paste-box['\"][^>]*>(?P<text>.*?)</textarea>",
    re.DOTALL,
)
_MTGTOP8_DEC_LINK_RE = re.compile(r"href=(?P<quote>['\"]?)(?P<href>dec\?[^'\"\s>]+)(?P=quote)", re.IGNORECASE)
_TAPPEDOUT_TEXTAREA_RE = re.compile(
    r"<textarea[^>]*id=['\"]mtga-textarea['\"][^>]*>(?P<text>.*?)</textarea>",
    re.DOTALL,
)
_AETHERHUB_OG_TITLE_RE = re.compile(
    r"<meta[^>]*property=['\"]og:title['\"][^>]*content=['\"](?P<title>.*?)['\"]",
    re.IGNORECASE | re.DOTALL,
)
_AETHERHUB_TITLE_RE = re.compile(r"<title>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_AETHERHUB_STRIP_BLOCKS_RE = re.compile(r"(?is)<(script|style|noscript|svg)\b.*?</\1>")
_AETHERHUB_BREAK_TAG_RE = re.compile(r"(?i)<br\s*/?>|</(?:tr|li|p|div|h[1-6]|section|article|header|footer)>")
_AETHERHUB_TAG_RE = re.compile(r"<[^>]+>")
_AETHERHUB_SECTION_LINE_RE = re.compile(
    r"^(?P<section>Commander|Companion|Main|Side)\s+\d+\s+cards?(?:\s+\(\d+\s+distinct\))?$",
    re.IGNORECASE,
)
_AETHERHUB_CARD_LINE_RE = re.compile(r"^(?P<quantity>\d+)\s+(?P<name>.+?)$")
_AETHERHUB_TRAILING_PRICE_RE = re.compile(r"\s+(?:\$|€)\d[\d.,]*$")
_MTGGOLDFISH_EXACT_LINE_RE = re.compile(
    r"^(?P<quantity>\d+)\s+"
    r"(?P<name>.+?)"
    r"(?:\s+<(?P<angle>[^>]+)>)?"
    r"\s+\[(?P<set_code>[A-Za-z0-9_-]+)\]"
    r"(?:\s+\((?P<finish_marker>F|FE)\))?$"
)
_MTGGOLDFISH_NAME_LINE_RE = re.compile(r"^Name\s+(?P<name>.+?)\s*$", re.IGNORECASE)
_MTGTOP8_NAME_LINE_RE = re.compile(r"^//\s*NAME\s*:\s*(?P<name>.+?)\s*$", re.IGNORECASE)
_MTGTOP8_CARD_LINE_RE = re.compile(
    r"^(?P<section>SB:)?\s*(?P<quantity>\d+)\s+\[(?P<set_code>[^\]]+)\]\s+(?P<name>.+?)\s*$"
)
_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT = (
    "Archidekt, AetherHub, ManaBox, Moxfield, MTGGoldfish, MTGTop8, and TappedOut"
)
_EXPORTED_DECKLIST_SECTION_HEADERS = {"deck", "mainboard", "main deck", "commander", "companion", "sideboard"}
_REMOTE_FETCH_TIMEOUT_SECONDS = 15
_REMOTE_FETCH_MAX_BYTES = 2 * 1024 * 1024
_REMOTE_FETCH_CHUNK_BYTES = 64 * 1024
_REMOTE_SOURCE_SNAPSHOT_VERSION = 1
_REMOTE_SOURCE_SNAPSHOT_TTL_SECONDS = 3600
_DEFAULT_REMOTE_SOURCE_SNAPSHOT_SIGNING_SECRET = "local-demo-deck-url-snapshot-secret"
_PROVIDER_DISPLAY_NAMES = {
    "archidekt": "Archidekt",
    "aetherhub": "AetherHub",
    "manabox": "ManaBox",
    "moxfield": "Moxfield",
    "mtggoldfish": "MTGGoldfish",
    "mtgtop8": "MTGTop8",
    "tappedout": "TappedOut",
}

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RemoteDeckCard:
    source_position: int
    quantity: int
    section: str
    scryfall_id: str | None
    finish: str
    name: str | None = None
    set_code: str | None = None
    collector_number: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteDeckSource:
    provider: str
    source_url: str
    deck_name: str | None
    cards: list[RemoteDeckCard]


@dataclass(frozen=True, slots=True)
class PlannedRemoteDeckImport:
    source: RemoteDeckSource
    rows_seen: int
    requested_card_quantity: int
    source_snapshot_token: str
    pending_rows: list[PendingImportRow]
    resolution_issues: list[RemoteDeckResolutionIssue]


@dataclass(frozen=True, slots=True)
class _ParsedMtgGoldfishExactEntry:
    source_position: int
    quantity: int
    name: str
    set_code: str
    collector_number: str | None
    finish: str
    block_index: int


@dataclass(frozen=True, slots=True)
class _RemoteDeckSourceError(Exception):
    code: str
    message: str
    provider: str | None = None
    source_url: str | None = None
    stage: str = "fetch"

    def __str__(self) -> str:
        return self.message


def _allowed_redirect_hosts_for_url(url: str) -> set[str]:
    hostname = (urlparse(url).hostname or "").lower()
    if not hostname:
        return set()
    for supported_hosts in (
        _ARCHIDEKT_HOSTS,
        _AETHERHUB_HOSTS,
        _MANABOX_HOSTS,
        _MOXFIELD_HOSTS,
        _MTGGOLDFISH_HOSTS,
        _MTGTOP8_HOSTS,
        _TAPPEDOUT_HOSTS,
    ):
        if hostname in supported_hosts:
            return set(supported_hosts)
    return {hostname}


def _remote_timeout_error(url: str) -> _RemoteDeckSourceError:
    return _RemoteDeckSourceError(
        code="timeout",
        message="Public deck URL fetch timed out.",
        source_url=url,
        stage="fetch",
    )


def _remote_unsupported_redirect_error(url: str, *, redirected_to: str) -> _RemoteDeckSourceError:
    return _RemoteDeckSourceError(
        code="unsupported_provider",
        message=f"Public deck URL redirected to unsupported host '{redirected_to}'.",
        source_url=url,
        stage="fetch",
    )


def _remote_payload_too_large_error(url: str) -> _RemoteDeckSourceError:
    return _RemoteDeckSourceError(
        code="unexpected_payload",
        message="Public deck URL returned a payload that exceeded the size limit.",
        source_url=url,
        stage="fetch",
    )


def _remote_http_error(url: str, exc: HTTPError) -> _RemoteDeckSourceError:
    if exc.code == 404:
        return _RemoteDeckSourceError(
            code="not_found",
            message="Public deck URL could not be fetched. Check that the deck exists and is publicly accessible.",
            source_url=url,
            stage="fetch",
        )
    if exc.code in {401, 403, 429}:
        return _RemoteDeckSourceError(
            code="private_or_blocked",
            message="Public deck URL could not be fetched because the deck is private or the provider blocked access.",
            source_url=url,
            stage="fetch",
        )
    if exc.code == 408:
        return _remote_timeout_error(url)
    return _RemoteDeckSourceError(
        code="upstream_error",
        message=f"Could not fetch public deck URL: HTTP {exc.code}.",
        source_url=url,
        stage="fetch",
    )


def _remote_transport_error(url: str) -> _RemoteDeckSourceError:
    return _RemoteDeckSourceError(
        code="upstream_error",
        message="Could not fetch public deck URL.",
        source_url=url,
        stage="fetch",
    )


def _is_timeout_exception(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def _read_remote_payload(response: Any, *, source_url: str) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = response.read(_REMOTE_FETCH_CHUNK_BYTES)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > _REMOTE_FETCH_MAX_BYTES:
            raise _remote_payload_too_large_error(source_url)
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_remote_redirect(url: str, *, final_url: str) -> None:
    allowed_hosts = _allowed_redirect_hosts_for_url(url)
    if not allowed_hosts:
        return
    final_hostname = (urlparse(final_url).hostname or "").lower()
    if final_hostname and final_hostname not in allowed_hosts:
        raise _remote_unsupported_redirect_error(url, redirected_to=final_hostname)


def _provider_display_name(provider: str) -> str:
    return _PROVIDER_DISPLAY_NAMES.get(provider, provider)


def _public_provider_error(provider: str, exc: _RemoteDeckSourceError) -> MtgStackError:
    provider_name = _provider_display_name(provider)
    if provider == "moxfield" and exc.code in {
        "private_or_blocked",
        "timeout",
        "unexpected_payload",
        "parse_drift",
        "upstream_error",
        "unsupported_provider",
    }:
        return ValidationError(
            "Moxfield deck URL could not be imported automatically. "
            "If the deck is public, export it from Moxfield and paste the deck text into /imports/decklist."
        )
    if exc.code == "not_found":
        return NotFoundError(
            f"{provider_name} deck URL could not be fetched. Check that the deck exists and is publicly accessible."
        )
    if exc.code == "private_or_blocked":
        return ValidationError(
            f"{provider_name} deck URL could not be fetched because the deck is private or the provider blocked automated access."
        )
    if exc.code == "timeout":
        return ValidationError(f"{provider_name} deck URL fetch timed out.")
    if exc.code == "unsupported_provider":
        return ValidationError(f"{provider_name} deck URL redirected to an unsupported host.")
    if exc.code == "parse_drift":
        return ValidationError(
            f"{provider_name} deck URL returned an unexpected payload shape. The provider page format may have changed."
        )
    if exc.code == "unexpected_payload":
        return ValidationError(f"{provider_name} deck URL returned an unexpected payload.")
    if exc.code == "upstream_error":
        return ValidationError(f"{provider_name} deck URL could not be fetched due to an upstream error.")
    return ValidationError(f"{provider_name} deck URL could not be fetched.")


def _log_remote_source_error(exc: _RemoteDeckSourceError) -> None:
    logger.warning(
        "remote_deck_import_failure provider=%s stage=%s code=%s source_url=%s message=%s",
        exc.provider or "unknown",
        exc.stage,
        exc.code,
        exc.source_url,
        exc.message,
    )


def _load_provider_remote_source(
    *,
    provider: str,
    source_url: str,
    loader: Callable[[], RemoteDeckSource],
) -> RemoteDeckSource:
    logger.info("remote_deck_fetch_start provider=%s source_url=%s", provider, source_url)
    try:
        source = loader()
    except _RemoteDeckSourceError as exc:
        wrapped = _RemoteDeckSourceError(
            code=exc.code,
            message=exc.message,
            provider=provider,
            source_url=source_url,
            stage=exc.stage,
        )
        _log_remote_source_error(wrapped)
        raise _public_provider_error(provider, wrapped) from exc
    except ValidationError as exc:
        wrapped = _RemoteDeckSourceError(
            code="parse_drift",
            message=str(exc),
            provider=provider,
            source_url=source_url,
            stage="parse",
        )
        _log_remote_source_error(wrapped)
        raise _public_provider_error(provider, wrapped) from exc

    logger.info(
        "remote_deck_fetch_success provider=%s source_url=%s deck_name=%s cards=%s",
        provider,
        source_url,
        source.deck_name,
        len(source.cards),
    )
    return source


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/plain,application/json,text/html",
            "User-Agent": "mtg-inventory-tool/1.0",
        },
    )
    try:
        with urlopen(request, timeout=_REMOTE_FETCH_TIMEOUT_SECONDS) as response:
            _validate_remote_redirect(url, final_url=response.geturl())
            payload = _read_remote_payload(response, source_url=url)
    except HTTPError as exc:
        raise _remote_http_error(url, exc) from exc
    except URLError as exc:
        if _is_timeout_exception(exc):
            raise _remote_timeout_error(url) from exc
        raise _remote_transport_error(url) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise _remote_timeout_error(url) from exc
    except OSError as exc:
        if _is_timeout_exception(exc):
            raise _remote_timeout_error(url) from exc
        raise _remote_transport_error(url) from exc

    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _RemoteDeckSourceError(
            code="unexpected_payload",
            message="Public deck URL returned an invalid text payload.",
            source_url=url,
            stage="fetch",
        ) from exc


def _fetch_json(url: str) -> Any:
    try:
        return json.loads(_fetch_text(url))
    except json.JSONDecodeError as exc:
        raise _RemoteDeckSourceError(
            code="unexpected_payload",
            message="Public deck URL returned an invalid JSON payload.",
            source_url=url,
            stage="fetch",
        ) from exc


def _remote_snapshot_payload(source: RemoteDeckSource) -> dict[str, Any]:
    return {
        "version": _REMOTE_SOURCE_SNAPSHOT_VERSION,
        "expires_at": int(time.time()) + _REMOTE_SOURCE_SNAPSHOT_TTL_SECONDS,
        "source": {
            "provider": source.provider,
            "source_url": source.source_url,
            "deck_name": source.deck_name,
            "cards": [
                {
                    "source_position": card.source_position,
                    "quantity": card.quantity,
                    "section": card.section,
                    "scryfall_id": card.scryfall_id,
                    "finish": card.finish,
                    "name": card.name,
                    "set_code": card.set_code,
                    "collector_number": card.collector_number,
                }
                for card in source.cards
            ],
        },
    }


def _normalize_snapshot_signing_secret(snapshot_signing_secret: str | None) -> str:
    if text_or_none(snapshot_signing_secret) is None:
        return _DEFAULT_REMOTE_SOURCE_SNAPSHOT_SIGNING_SECRET
    return text_or_none(snapshot_signing_secret) or _DEFAULT_REMOTE_SOURCE_SNAPSHOT_SIGNING_SECRET


def _snapshot_payload_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _snapshot_signature(payload: Mapping[str, Any], *, snapshot_signing_secret: str) -> str:
    return hmac.new(
        snapshot_signing_secret.encode("utf-8"),
        _snapshot_payload_bytes(payload),
        hashlib.sha256,
    ).hexdigest()


def _encode_remote_source_snapshot_token(
    source: RemoteDeckSource,
    *,
    snapshot_signing_secret: str | None = None,
) -> str:
    payload = _remote_snapshot_payload(source)
    container = {
        "payload": payload,
        "signature": _snapshot_signature(
            payload,
            snapshot_signing_secret=_normalize_snapshot_signing_secret(snapshot_signing_secret),
        ),
    }
    return base64.urlsafe_b64encode(_snapshot_payload_bytes(container)).decode("ascii")


def _decode_remote_source_snapshot_token(
    source_snapshot_token: str,
    *,
    source_url: str,
    snapshot_signing_secret: str | None = None,
) -> RemoteDeckSource:
    token_text = text_or_none(source_snapshot_token)
    if token_text is None:
        raise ValidationError("source_snapshot_token is required.")
    try:
        padded_token = token_text + "=" * (-len(token_text) % 4)
        container = json.loads(base64.urlsafe_b64decode(padded_token.encode("ascii")).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValidationError("source_snapshot_token is invalid.") from exc

    if not isinstance(container, dict):
        raise ValidationError("source_snapshot_token is invalid.")
    payload = container.get("payload")
    signature = text_or_none(container.get("signature"))
    if not isinstance(payload, dict) or signature is None:
        raise ValidationError("source_snapshot_token is invalid.")
    expected_signature = _snapshot_signature(
        payload,
        snapshot_signing_secret=_normalize_snapshot_signing_secret(snapshot_signing_secret),
    )
    if not hmac.compare_digest(signature, expected_signature):
        raise ValidationError("source_snapshot_token is invalid.")

    if payload.get("version") != _REMOTE_SOURCE_SNAPSHOT_VERSION:
        raise ValidationError("source_snapshot_token version is unsupported. Re-run preview.")

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, int):
        raise ValidationError("source_snapshot_token is invalid.")
    if expires_at < int(time.time()):
        raise ValidationError("source_snapshot_token has expired. Re-run preview.")

    raw_source = payload.get("source")
    if not isinstance(raw_source, dict):
        raise ValidationError("source_snapshot_token is invalid.")
    token_source_url = text_or_none(raw_source.get("source_url"))
    if token_source_url != source_url:
        raise ValidationError("source_snapshot_token does not match the requested source_url.")

    provider = text_or_none(raw_source.get("provider"))
    if provider is None:
        raise ValidationError("source_snapshot_token is invalid.")
    raw_cards = raw_source.get("cards")
    if not isinstance(raw_cards, list):
        raise ValidationError("source_snapshot_token is invalid.")

    cards: list[RemoteDeckCard] = []
    for raw_card in raw_cards:
        if not isinstance(raw_card, dict):
            raise ValidationError("source_snapshot_token is invalid.")
        try:
            source_position = int(raw_card.get("source_position"))
            quantity = int(raw_card.get("quantity"))
        except (TypeError, ValueError) as exc:
            raise ValidationError("source_snapshot_token is invalid.") from exc
        section = text_or_none(raw_card.get("section"))
        finish = text_or_none(raw_card.get("finish"))
        if section is None or finish is None:
            raise ValidationError("source_snapshot_token is invalid.")
        cards.append(
            RemoteDeckCard(
                source_position=source_position,
                quantity=quantity,
                section=section,
                scryfall_id=text_or_none(raw_card.get("scryfall_id")),
                finish=normalize_finish(finish),
                name=text_or_none(raw_card.get("name")),
                set_code=text_or_none(raw_card.get("set_code")),
                collector_number=text_or_none(raw_card.get("collector_number")),
            )
        )

    return RemoteDeckSource(
        provider=provider,
        source_url=token_source_url,
        deck_name=text_or_none(raw_source.get("deck_name")),
        cards=cards,
    )


def _load_remote_source_for_import(
    source_url: str,
    *,
    source_snapshot_token: str | None = None,
    snapshot_signing_secret: str | None = None,
) -> tuple[RemoteDeckSource, str]:
    if text_or_none(source_snapshot_token) is not None:
        source = _decode_remote_source_snapshot_token(
            text_or_none(source_snapshot_token) or "",
            source_url=source_url,
            snapshot_signing_secret=snapshot_signing_secret,
        )
        return source, text_or_none(source_snapshot_token) or ""

    source = fetch_remote_deck_source(source_url)
    return source, _encode_remote_source_snapshot_token(
        source,
        snapshot_signing_secret=snapshot_signing_secret,
    )


def _parse_remote_deck_url(source_url: str) -> Any:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError("deck URL must begin with http:// or https://.")
    return parsed


def _normalize_remote_finish(value: str | None) -> str:
    text = text_or_none(value)
    if text is None:
        return DEFAULT_FINISH

    normalized = text.strip().lower().replace("-", " ")
    if normalized == "etched foil":
        normalized = "etched"
    if normalized == "non foil":
        normalized = "nonfoil"
    return normalize_finish(normalized.replace(" ", ""))


def _archidekt_deck_id_from_url(source_url: str) -> str:
    parsed = _parse_remote_deck_url(source_url)
    if (parsed.hostname or "").lower() not in _ARCHIDEKT_HOSTS:
        raise ValidationError(f"Only {_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT} deck URLs are supported right now.")
    match = _ARCHIDEKT_DECK_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValidationError("Archidekt deck URL must look like https://archidekt.com/decks/<deck_id>/...")
    return match.group("deck_id")


def _moxfield_public_id_from_url(source_url: str) -> str:
    parsed = _parse_remote_deck_url(source_url)
    if (parsed.hostname or "").lower() not in _MOXFIELD_HOSTS:
        raise ValidationError(f"Only {_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT} deck URLs are supported right now.")
    match = _MOXFIELD_DECK_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValidationError("Moxfield deck URL must look like https://moxfield.com/decks/<public_id>/...")
    return match.group("public_id")


def _aetherhub_deck_slug_from_url(source_url: str) -> str:
    parsed = _parse_remote_deck_url(source_url)
    if (parsed.hostname or "").lower() not in _AETHERHUB_HOSTS:
        raise ValidationError(f"Only {_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT} deck URLs are supported right now.")
    match = _AETHERHUB_DECK_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValidationError(
            "AetherHub deck URL must look like https://aetherhub.com/Deck/<deck-slug> "
            "or https://aetherhub.com/Metagame/<format>/Deck/<deck-slug>."
        )
    return match.group("deck_slug")


def _manabox_deck_id_from_url(source_url: str) -> str:
    parsed = _parse_remote_deck_url(source_url)
    if (parsed.hostname or "").lower() not in _MANABOX_HOSTS:
        raise ValidationError(f"Only {_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT} deck URLs are supported right now.")
    match = _MANABOX_DECK_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValidationError("ManaBox deck URL must look like https://manabox.app/decks/<deck_id>.")
    return match.group("deck_id")


def _extract_mtggoldfish_download_id(page_html: str) -> str:
    match = _MTGGOLDFISH_DOWNLOAD_ID_RE.search(page_html)
    if match is None:
        raise ValidationError("MTGGoldfish deck URL did not expose a downloadable deck id.")
    return match.group("deck_id")


def _mtggoldfish_deck_id_from_url(source_url: str) -> str:
    parsed = _parse_remote_deck_url(source_url)
    if (parsed.hostname or "").lower() not in _MTGGOLDFISH_HOSTS:
        raise ValidationError(f"Only {_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT} deck URLs are supported right now.")

    for pattern in (
        _MTGGOLDFISH_ARENA_DOWNLOAD_PATH_RE,
        _MTGGOLDFISH_DOWNLOAD_PATH_RE,
        _MTGGOLDFISH_DECK_PATH_RE,
    ):
        match = pattern.fullmatch(parsed.path)
        if match is not None:
            return match.group("deck_id")

    page_html = _fetch_text(source_url)
    return _extract_mtggoldfish_download_id(page_html)


def _tappedout_deck_slug_from_url(source_url: str) -> str:
    parsed = _parse_remote_deck_url(source_url)
    if (parsed.hostname or "").lower() not in _TAPPEDOUT_HOSTS:
        raise ValidationError(f"Only {_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT} deck URLs are supported right now.")
    match = _TAPPEDOUT_DECK_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValidationError("TappedOut deck URL must look like https://tappedout.net/mtg-decks/<deck-slug>/...")
    return match.group("deck_slug")


def _extract_mtgtop8_dec_href(page_html: str) -> str:
    match = _MTGTOP8_DEC_LINK_RE.search(page_html)
    if match is None:
        raise ValidationError("MTGTop8 deck URL did not expose a downloadable .dec export.")
    return unescape(match.group("href"))


def _mtgtop8_dec_export_url_from_url(source_url: str) -> str:
    parsed = _parse_remote_deck_url(source_url)
    if (parsed.hostname or "").lower() not in _MTGTOP8_HOSTS:
        raise ValidationError(f"Only {_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT} deck URLs are supported right now.")

    query = parse_qs(parsed.query)
    deck_id = text_or_none((query.get("d") or [None])[0])
    export_name = text_or_none((query.get("f") or [None])[0])
    if deck_id is not None and export_name is not None:
        return f"https://www.mtgtop8.com/dec?{urlencode({'d': deck_id, 'f': export_name})}"

    page_html = _fetch_text(source_url)
    return urljoin("https://www.mtgtop8.com/", _extract_mtgtop8_dec_href(page_html))


def _archidekt_section_for_card(
    *,
    categories: list[str],
    category_flags: dict[str, bool],
    companion: bool,
) -> str | None:
    normalized = {category.strip().lower() for category in categories if category.strip()}
    if companion or "companion" in normalized:
        return "companion"
    if "commander" in normalized:
        return "commander"
    if "sideboard" in normalized:
        return "sideboard"

    included_categories = [category for category in categories if category_flags.get(category, True)]
    if not included_categories:
        return None
    return "mainboard"


def _archidekt_card_to_remote_card(
    card_payload: dict[str, Any],
    *,
    source_position: int,
    category_flags: dict[str, bool],
) -> RemoteDeckCard | None:
    raw_categories = card_payload.get("categories") or []
    if not isinstance(raw_categories, list):
        raise ValidationError(f"Archidekt card {source_position}: categories payload must be a list.")
    categories = [str(category) for category in raw_categories]
    section = _archidekt_section_for_card(
        categories=categories,
        category_flags=category_flags,
        companion=bool(card_payload.get("companion")),
    )
    if section is None:
        return None

    quantity = int(card_payload.get("quantity") or 0)
    if quantity <= 0:
        raise ValidationError(f"Archidekt card {source_position}: quantity must be a positive integer.")

    card = card_payload.get("card")
    if not isinstance(card, dict):
        raise ValidationError(f"Archidekt card {source_position}: card payload is missing.")
    scryfall_id = text_or_none(card.get("uid"))
    if scryfall_id is None:
        raise ValidationError(f"Archidekt card {source_position}: card payload is missing a printing identifier.")

    finish = _normalize_remote_finish(text_or_none(card_payload.get("modifier")))
    return RemoteDeckCard(
        source_position=source_position,
        quantity=quantity,
        section=section,
        scryfall_id=scryfall_id,
        finish=finish,
    )


def _remote_source_from_archidekt_payload(source_url: str, payload: dict[str, Any]) -> RemoteDeckSource:
    raw_cards = payload.get("cards")
    if not isinstance(raw_cards, list):
        raise ValidationError("Archidekt payload is missing the deck card list.")

    raw_categories = payload.get("categories") or []
    category_flags: dict[str, bool] = {}
    if isinstance(raw_categories, list):
        for category in raw_categories:
            if not isinstance(category, dict):
                continue
            name = text_or_none(category.get("name"))
            if name is None:
                continue
            category_flags[name] = bool(category.get("includedInDeck", True))

    cards: list[RemoteDeckCard] = []
    for source_position, card_payload in enumerate(raw_cards, start=1):
        if not isinstance(card_payload, dict):
            raise ValidationError(f"Archidekt card {source_position}: invalid card payload.")
        remote_card = _archidekt_card_to_remote_card(
            card_payload,
            source_position=source_position,
            category_flags=category_flags,
        )
        if remote_card is None:
            continue
        cards.append(remote_card)

    if not cards:
        raise ValidationError("No importable deck cards were found at that URL.")

    return RemoteDeckSource(
        provider="archidekt",
        source_url=source_url,
        deck_name=text_or_none(payload.get("name")),
        cards=cards,
    )


def _moxfield_entry_to_remote_card(
    entry_payload: dict[str, Any],
    *,
    source_position: int,
    section: str,
) -> RemoteDeckCard:
    quantity = int(entry_payload.get("quantity") or 0)
    if quantity <= 0:
        raise ValidationError(f"Moxfield card {source_position}: quantity must be a positive integer.")

    card = entry_payload.get("card")
    if not isinstance(card, dict):
        raise ValidationError(f"Moxfield card {source_position}: card payload is missing.")

    scryfall_id = text_or_none(card.get("scryfall_id"))
    if scryfall_id is None:
        raise ValidationError(f"Moxfield card {source_position}: card payload is missing a printing identifier.")

    raw_finish = text_or_none(entry_payload.get("finish"))
    if raw_finish is None and bool(entry_payload.get("isFoil")):
        raw_finish = "foil"
    if raw_finish is None:
        raw_finish = text_or_none(card.get("defaultFinish")) or DEFAULT_FINISH

    return RemoteDeckCard(
        source_position=source_position,
        quantity=quantity,
        section=section,
        scryfall_id=scryfall_id,
        finish=_normalize_remote_finish(raw_finish),
    )


def _moxfield_entries_to_remote_cards(
    raw_entries: Any,
    *,
    section: str,
    next_source_position: int,
) -> tuple[list[RemoteDeckCard], int]:
    if raw_entries is None:
        return [], next_source_position
    if not isinstance(raw_entries, dict):
        raise ValidationError(f"Moxfield {section} payload must be an object keyed by card id.")

    cards: list[RemoteDeckCard] = []
    source_position = next_source_position
    for entry_payload in raw_entries.values():
        if not isinstance(entry_payload, dict):
            raise ValidationError(f"Moxfield card {source_position}: invalid card payload.")
        cards.append(
            _moxfield_entry_to_remote_card(
                entry_payload,
                source_position=source_position,
                section=section,
            )
        )
        source_position += 1
    return cards, source_position


def _remote_source_from_moxfield_payload(source_url: str, payload: dict[str, Any]) -> RemoteDeckSource:
    cards: list[RemoteDeckCard] = []
    source_position = 1
    board_sections = (
        ("commanders", "commander"),
        ("companions", "companion"),
        ("signatureSpells", "signature-spell"),
        ("mainboard", "mainboard"),
        ("sideboard", "sideboard"),
        ("attractions", "attraction"),
        ("stickers", "sticker"),
    )

    for payload_key, section in board_sections:
        section_cards, source_position = _moxfield_entries_to_remote_cards(
            payload.get(payload_key),
            section=section,
            next_source_position=source_position,
        )
        cards.extend(section_cards)

    if not cards:
        raise ValidationError("No importable deck cards were found at that URL.")

    return RemoteDeckSource(
        provider="moxfield",
        source_url=source_url,
        deck_name=text_or_none(payload.get("name")),
        cards=cards,
    )


def _decode_manabox_astro_value(value: Any) -> Any:
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], int):
            type_code, payload = value
            if type_code == 0:
                return _decode_manabox_astro_value(payload)
            if type_code == 1:
                if not isinstance(payload, list):
                    raise ValidationError("ManaBox deck payload included an invalid array value.")
                return [_decode_manabox_astro_value(item) for item in payload]
            return payload
        return [_decode_manabox_astro_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _decode_manabox_astro_value(raw_value) for key, raw_value in value.items()}
    return value


def _extract_manabox_main_props(page_html: str) -> dict[str, Any]:
    match = _MANABOX_MAIN_PROPS_RE.search(page_html)
    if match is None:
        raise ValidationError("ManaBox deck page did not include an importable deck payload.")
    try:
        return _decode_manabox_astro_value(json.loads(unescape(match.group("props"))))
    except json.JSONDecodeError as exc:
        raise ValidationError("ManaBox deck page exposed an invalid deck payload.") from exc


def _manabox_section_for_board_category(source_position: int, board_category: Any) -> str | None:
    try:
        category_value = int(board_category)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"ManaBox card {source_position}: board category must be an integer.") from exc

    if category_value in _MANABOX_SKIPPED_BOARD_CATEGORIES:
        return None
    section = _MANABOX_BOARD_CATEGORY_TO_SECTION.get(category_value)
    if section is None:
        raise ValidationError(
            f"ManaBox card {source_position}: unsupported board category '{category_value}'."
        )
    return section


def _remote_source_from_manabox_page(source_url: str, *, page_html: str) -> RemoteDeckSource:
    payload = _extract_manabox_main_props(page_html)
    deck = payload.get("deck")
    if not isinstance(deck, dict):
        raise ValidationError("ManaBox deck page did not include a valid deck object.")

    raw_cards = deck.get("cards")
    if not isinstance(raw_cards, list):
        raise ValidationError("ManaBox deck page did not include the deck card list.")

    cards: list[RemoteDeckCard] = []
    for source_position, raw_card in enumerate(raw_cards, start=1):
        if not isinstance(raw_card, dict):
            raise ValidationError(f"ManaBox card {source_position}: invalid card payload.")

        section = _manabox_section_for_board_category(source_position, raw_card.get("boardCategory"))
        if section is None:
            continue

        quantity = int(raw_card.get("quantity") or 0)
        if quantity <= 0:
            raise ValidationError(f"ManaBox card {source_position}: quantity must be a positive integer.")

        name = text_or_none(raw_card.get("name"))
        if name is None:
            raise ValidationError(f"ManaBox card {source_position}: card name is required.")

        cards.append(
            RemoteDeckCard(
                source_position=source_position,
                quantity=quantity,
                section=section,
                scryfall_id=None,
                finish=_normalize_remote_finish(text_or_none(raw_card.get("variant"))),
                name=name,
                set_code=(text_or_none(raw_card.get("setId")) or "").upper() or None,
                collector_number=text_or_none(raw_card.get("collectorNumber")),
            )
        )

    if not cards:
        raise ValidationError("No importable deck cards were found at that URL.")

    return RemoteDeckSource(
        provider="manabox",
        source_url=source_url,
        deck_name=text_or_none(deck.get("name")),
        cards=cards,
    )


def _extract_mtggoldfish_textarea(page_html: str) -> str:
    match = _MTGGOLDFISH_TEXTAREA_RE.search(page_html)
    if match is None:
        raise ValidationError("MTGGoldfish export page did not include a decklist text area.")
    return unescape(match.group("text"))


def _extract_tappedout_textarea(page_html: str) -> str:
    match = _TAPPEDOUT_TEXTAREA_RE.search(page_html)
    if match is None:
        raise ValidationError("TappedOut deck page did not include an MTG Arena export text area.")
    return unescape(match.group("text"))


def _extract_aetherhub_deck_name(page_html: str) -> str | None:
    for pattern in (_AETHERHUB_OG_TITLE_RE, _AETHERHUB_TITLE_RE):
        match = pattern.search(page_html)
        if match is None:
            continue
        title = " ".join(unescape(match.group("title")).replace("\xa0", " ").split())
        for suffix in (" - AetherHub", " | AetherHub", " • AetherHub"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
        if title and title != "Just a moment...":
            return title
    return None


def _extract_aetherhub_text_lines(page_html: str) -> list[str]:
    text = _AETHERHUB_STRIP_BLOCKS_RE.sub("\n", page_html)
    text = _AETHERHUB_BREAK_TAG_RE.sub("\n", text)
    text = _AETHERHUB_TAG_RE.sub(" ", text)
    text = unescape(text).replace("\xa0", " ")
    return [" ".join(raw_line.split()) for raw_line in text.splitlines() if raw_line.split()]


def _aetherhub_section_header_for_label(section: str) -> str:
    if section == "mainboard":
        return "Deck"
    return section.replace("-", " ").title()


def _aetherhub_section_from_line(value: str) -> str | None:
    match = _AETHERHUB_SECTION_LINE_RE.fullmatch(value)
    if match is None:
        return None
    normalized = match.group("section").strip().lower()
    if normalized == "main":
        return "mainboard"
    if normalized == "side":
        return "sideboard"
    return normalized


def _aetherhub_card_line_for_text(value: str) -> str | None:
    match = _AETHERHUB_CARD_LINE_RE.fullmatch(value)
    if match is None:
        return None

    name = match.group("name").strip()
    name = re.split(r"\s+\|\s+", name, maxsplit=1)[0].strip()
    name = _AETHERHUB_TRAILING_PRICE_RE.sub("", name).strip()
    if not name:
        return None
    return f"{int(match.group('quantity'))} {name}"


def _parse_aetherhub_decklist(page_html: str) -> tuple[str | None, list[ParsedDecklistEntry]]:
    if "Enable JavaScript and cookies to continue" in page_html or "<title>Just a moment...</title>" in page_html:
        raise ValidationError(
            "AetherHub blocked automated access to that public deck URL. Try again later or use pasted deck text."
        )

    deck_lines: list[str] = []
    seen_sections: set[str] = set()
    current_section: str | None = None
    for line in _extract_aetherhub_text_lines(page_html):
        section = _aetherhub_section_from_line(line)
        if section is not None:
            if deck_lines and section in seen_sections:
                break
            seen_sections.add(section)
            current_section = section
            deck_lines.append(_aetherhub_section_header_for_label(section))
            continue

        if current_section is None:
            continue

        card_line = _aetherhub_card_line_for_text(line)
        if card_line is None:
            continue
        deck_lines.append(card_line)

    if not deck_lines:
        raise ValidationError("AetherHub deck page did not include a parseable decklist.")
    return _extract_aetherhub_deck_name(page_html), parse_decklist_text("\n".join(deck_lines))


def _is_exported_decklist_section_header(value: str) -> bool:
    normalized = " ".join(value.strip().rstrip(":").lower().split())
    return normalized in _EXPORTED_DECKLIST_SECTION_HEADERS


def _parse_exported_decklist_entries(deck_text: str, *, provider_name: str) -> tuple[str | None, list[ParsedDecklistEntry]]:
    deck_name: str | None = None
    deck_lines: list[str] = []

    for raw_line in deck_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if deck_lines:
                deck_lines.append("")
            continue
        if deck_name is None:
            name_match = _MTGGOLDFISH_NAME_LINE_RE.fullmatch(stripped)
            if name_match is not None:
                deck_name = name_match.group("name").strip()
                continue
        if not deck_lines and not _is_exported_decklist_section_header(stripped):
            continue
        deck_lines.append(stripped)

    if not deck_lines:
        raise ValidationError(f"{provider_name} export did not include a parseable decklist.")
    return deck_name, parse_decklist_text("\n".join(deck_lines))


def _parse_mtggoldfish_arena_entries(page_html: str) -> tuple[str | None, list[ParsedDecklistEntry]]:
    return _parse_exported_decklist_entries(
        _extract_mtggoldfish_textarea(page_html),
        provider_name="MTGGoldfish",
    )


def _parse_mtggoldfish_finish_marker(marker: str | None) -> str:
    if marker == "F":
        return "foil"
    if marker == "FE":
        return "etched"
    return DEFAULT_FINISH


def _parse_mtggoldfish_collector_number(angle_value: str | None) -> str | None:
    text = text_or_none(angle_value)
    if text is None:
        return None
    if re.fullmatch(r"[0-9][0-9A-Za-z/-]*", text) is None:
        return None
    return text


def _parse_mtggoldfish_exact_entries(download_text: str) -> list[_ParsedMtgGoldfishExactEntry]:
    entries: list[_ParsedMtgGoldfishExactEntry] = []
    block_index = 0
    saw_card_in_block = False
    source_position = 1

    for raw_line in download_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if saw_card_in_block:
                block_index += 1
                saw_card_in_block = False
            continue

        match = _MTGGOLDFISH_EXACT_LINE_RE.fullmatch(stripped)
        if match is None:
            raise ValidationError(
                f"MTGGoldfish exact export line {source_position}: unsupported card line '{stripped}'."
            )

        entries.append(
            _ParsedMtgGoldfishExactEntry(
                source_position=source_position,
                quantity=int(match.group("quantity")),
                name=match.group("name").strip(),
                set_code=match.group("set_code").upper(),
                collector_number=_parse_mtggoldfish_collector_number(match.group("angle")),
                finish=_parse_mtggoldfish_finish_marker(match.group("finish_marker")),
                block_index=block_index,
            )
        )
        source_position += 1
        saw_card_in_block = True

    if not entries:
        raise ValidationError("No importable deck cards were found at that URL.")
    return entries


def _consume_matching_section(
    remaining_sections: dict[tuple[str, int], list[str]],
    *,
    name: str,
    quantity: int,
    block_index: int,
) -> str:
    key = (name.casefold(), quantity)
    options = remaining_sections.get(key) or []

    if block_index > 0:
        if "sideboard" in options:
            options.remove("sideboard")
        return "sideboard"

    if not options:
        return "mainboard"
    if len(options) == 1:
        return options.pop(0)

    non_mainboard = [section for section in options if section != "mainboard"]
    if len(non_mainboard) == 1:
        chosen = non_mainboard[0]
        options.remove(chosen)
        return chosen

    if "mainboard" in options:
        options.remove("mainboard")
        return "mainboard"
    return options.pop(0)


def _remote_source_from_mtggoldfish_downloads(
    source_url: str,
    *,
    arena_page_html: str,
    exact_download_text: str,
) -> RemoteDeckSource:
    deck_name, arena_entries = _parse_mtggoldfish_arena_entries(arena_page_html)
    remaining_sections: dict[tuple[str, int], list[str]] = {}
    for entry in arena_entries:
        key = (entry.name.casefold(), entry.quantity)
        remaining_sections.setdefault(key, []).append(entry.section)

    cards: list[RemoteDeckCard] = []
    for entry in _parse_mtggoldfish_exact_entries(exact_download_text):
        section = _consume_matching_section(
            remaining_sections,
            name=entry.name,
            quantity=entry.quantity,
            block_index=entry.block_index,
        )
        cards.append(
            RemoteDeckCard(
                source_position=entry.source_position,
                quantity=entry.quantity,
                section=section,
                scryfall_id=None,
                finish=entry.finish,
                name=entry.name,
                set_code=entry.set_code,
                collector_number=entry.collector_number,
            )
        )

    return RemoteDeckSource(
        provider="mtggoldfish",
        source_url=source_url,
        deck_name=deck_name,
        cards=cards,
    )


def _remote_source_from_tappedout_page(source_url: str, *, page_html: str) -> RemoteDeckSource:
    deck_name, entries = _parse_exported_decklist_entries(
        _extract_tappedout_textarea(page_html),
        provider_name="TappedOut",
    )

    cards = [
        RemoteDeckCard(
            source_position=entry.line_number,
            quantity=entry.quantity,
            section=entry.section,
            scryfall_id=None,
            finish=DEFAULT_FINISH,
            name=entry.name,
            set_code=entry.set_code,
            collector_number=entry.collector_number,
        )
        for entry in entries
    ]
    if not cards:
        raise ValidationError("No importable deck cards were found at that URL.")

    return RemoteDeckSource(
        provider="tappedout",
        source_url=source_url,
        deck_name=deck_name,
        cards=cards,
    )


def _remote_source_from_aetherhub_page(source_url: str, *, page_html: str) -> RemoteDeckSource:
    deck_name, entries = _parse_aetherhub_decklist(page_html)
    cards = [
        RemoteDeckCard(
            source_position=source_position,
            quantity=entry.quantity,
            section=entry.section,
            scryfall_id=None,
            finish=DEFAULT_FINISH,
            name=entry.name,
        )
        for source_position, entry in enumerate(entries, start=1)
    ]
    if not cards:
        raise ValidationError("No importable deck cards were found at that URL.")

    return RemoteDeckSource(
        provider="aetherhub",
        source_url=source_url,
        deck_name=deck_name,
        cards=cards,
    )


def _remote_source_from_mtgtop8_export(source_url: str, *, export_text: str) -> RemoteDeckSource:
    deck_name: str | None = None
    cards: list[RemoteDeckCard] = []
    source_position = 1

    for raw_line in export_text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        name_match = _MTGTOP8_NAME_LINE_RE.fullmatch(stripped)
        if name_match is not None:
            deck_name = name_match.group("name").strip()
            continue
        if stripped.startswith("//"):
            continue

        match = _MTGTOP8_CARD_LINE_RE.fullmatch(stripped)
        if match is None:
            raise ValidationError(f"MTGTop8 export line {source_position}: unsupported card line '{stripped}'.")

        cards.append(
            RemoteDeckCard(
                source_position=source_position,
                quantity=int(match.group("quantity")),
                section="sideboard" if match.group("section") is not None else "mainboard",
                scryfall_id=None,
                finish=DEFAULT_FINISH,
                name=match.group("name").strip(),
                set_code=match.group("set_code").strip().upper(),
            )
        )
        source_position += 1

    if not cards:
        raise ValidationError("No importable deck cards were found at that URL.")

    return RemoteDeckSource(
        provider="mtgtop8",
        source_url=source_url,
        deck_name=deck_name,
        cards=cards,
    )


def _archidekt_payload_for_deck_id(deck_id: str) -> dict[str, Any]:
    payload = _fetch_json(f"https://archidekt.com/api/decks/{deck_id}/")
    if not isinstance(payload, dict):
        raise _RemoteDeckSourceError(
            code="unexpected_payload",
            message="Public deck URL returned an unexpected JSON payload shape.",
            stage="fetch",
        )
    return payload


def _moxfield_payload_for_public_id(public_id: str) -> dict[str, Any]:
    payload = _fetch_json(f"https://api2.moxfield.com/v2/decks/all/{public_id}")
    if not isinstance(payload, dict):
        raise _RemoteDeckSourceError(
            code="unexpected_payload",
            message="Public deck URL returned an unexpected JSON payload shape.",
            stage="fetch",
        )
    return payload


def _remote_source_from_mtggoldfish_url(source_url: str) -> RemoteDeckSource:
    deck_id = _mtggoldfish_deck_id_from_url(source_url)
    return _remote_source_from_mtggoldfish_downloads(
        source_url,
        arena_page_html=_fetch_text(f"https://www.mtggoldfish.com/deck/arena_download/{deck_id}"),
        exact_download_text=_fetch_text(
            f"https://www.mtggoldfish.com/deck/download/{deck_id}?output=mtggoldfish&type=tabletop"
        ),
    )


def _remote_source_from_mtgtop8_url(source_url: str) -> RemoteDeckSource:
    return _remote_source_from_mtgtop8_export(
        source_url,
        export_text=_fetch_text(_mtgtop8_dec_export_url_from_url(source_url)),
    )


def fetch_remote_deck_source(source_url: str) -> RemoteDeckSource:
    parsed = _parse_remote_deck_url(source_url)
    hostname = (parsed.hostname or "").lower()

    if hostname in _ARCHIDEKT_HOSTS:
        deck_id = _archidekt_deck_id_from_url(source_url)
        return _load_provider_remote_source(
            provider="archidekt",
            source_url=source_url,
            loader=lambda: _remote_source_from_archidekt_payload(
                source_url,
                _archidekt_payload_for_deck_id(deck_id),
            ),
        )

    if hostname in _AETHERHUB_HOSTS:
        deck_slug = _aetherhub_deck_slug_from_url(source_url)
        return _load_provider_remote_source(
            provider="aetherhub",
            source_url=source_url,
            loader=lambda: _remote_source_from_aetherhub_page(
                source_url,
                page_html=_fetch_text(f"https://aetherhub.com/Deck/{deck_slug}"),
            ),
        )

    if hostname in _MANABOX_HOSTS:
        deck_id = _manabox_deck_id_from_url(source_url)
        return _load_provider_remote_source(
            provider="manabox",
            source_url=source_url,
            loader=lambda: _remote_source_from_manabox_page(
                source_url,
                page_html=_fetch_text(f"https://manabox.app/decks/{deck_id}"),
            ),
        )

    if hostname in _MOXFIELD_HOSTS:
        public_id = _moxfield_public_id_from_url(source_url)
        return _load_provider_remote_source(
            provider="moxfield",
            source_url=source_url,
            loader=lambda: _remote_source_from_moxfield_payload(
                source_url,
                _moxfield_payload_for_public_id(public_id),
            ),
        )

    if hostname in _MTGGOLDFISH_HOSTS:
        return _load_provider_remote_source(
            provider="mtggoldfish",
            source_url=source_url,
            loader=lambda: _remote_source_from_mtggoldfish_url(source_url),
        )

    if hostname in _MTGTOP8_HOSTS:
        return _load_provider_remote_source(
            provider="mtgtop8",
            source_url=source_url,
            loader=lambda: _remote_source_from_mtgtop8_url(source_url),
        )

    if hostname in _TAPPEDOUT_HOSTS:
        deck_slug = _tappedout_deck_slug_from_url(source_url)
        return _load_provider_remote_source(
            provider="tappedout",
            source_url=source_url,
            loader=lambda: _remote_source_from_tappedout_page(
                source_url,
                page_html=_fetch_text(f"https://tappedout.net/mtg-decks/{deck_slug}/"),
            ),
        )

    raise ValidationError(f"Only {_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT} deck URLs are supported right now.")


def _build_add_card_kwargs_from_remote_card(
    card: RemoteDeckCard,
    *,
    default_inventory: str | None,
    printing_selection_mode: str = "explicit",
) -> dict[str, Any]:
    inventory_slug = text_or_none(default_inventory)
    if inventory_slug is None:
        raise ValidationError("default_inventory is required for deck URL imports.")
    if card.scryfall_id is None and text_or_none(card.name) is None:
        raise ValidationError("Remote deck import requires either a printing id or a card name.")
    return {
        "inventory_slug": inventory_slug,
        "inventory_display_name": None,
        "scryfall_id": card.scryfall_id,
        "oracle_id": None,
        "tcgplayer_product_id": None,
        "name": card.name,
        "set_code": card.set_code,
        "collector_number": card.collector_number,
        "lang": None,
        "quantity": card.quantity,
        "condition_code": DEFAULT_CONDITION_CODE,
        "finish": card.finish,
        "language_code": None,
        "location": "",
        "acquisition_price": None,
        "acquisition_currency": None,
        "notes": None,
        "tags": None,
        "printing_selection_mode": printing_selection_mode,
    }


def _build_pending_remote_row(
    card: RemoteDeckCard,
    *,
    default_inventory: str | None,
    printing_selection_mode: str,
) -> PendingImportRow:
    return PendingImportRow(
        row_number=card.source_position,
        add_kwargs=_build_add_card_kwargs_from_remote_card(
            card,
            default_inventory=default_inventory,
            printing_selection_mode=printing_selection_mode,
        ),
        response_metadata={"source_position": card.source_position, "section": card.section},
        error_label="Remote deck card",
    )


def _remote_card_with_resolved_printing(
    card: RemoteDeckCard,
    *,
    scryfall_id: str,
    finish: str | None = None,
) -> RemoteDeckCard:
    return RemoteDeckCard(
        source_position=card.source_position,
        quantity=card.quantity,
        section=card.section,
        scryfall_id=scryfall_id,
        finish=finish or card.finish,
    )


def _build_remote_requested_card(card: RemoteDeckCard) -> RemoteDeckRequestedCard:
    return RemoteDeckRequestedCard(
        name=card.name,
        quantity=card.quantity,
        set_code=card.set_code,
        collector_number=card.collector_number,
        finish=card.finish,
    )


def _normalize_remote_resolution_selections(
    resolutions: list[Mapping[str, Any]] | None,
) -> dict[int, RemoteDeckResolutionSelection]:
    if not resolutions:
        return {}

    normalized: dict[int, RemoteDeckResolutionSelection] = {}
    for raw_selection in resolutions:
        source_position = raw_selection.get("source_position")
        if not isinstance(source_position, int):
            raise ValidationError("Each remote deck resolution must include an integer source_position.")
        if source_position in normalized:
            raise ValidationError("remote deck resolutions must not repeat the same source_position.")
        scryfall_id = text_or_none(raw_selection.get("scryfall_id"))
        if scryfall_id is None:
            raise ValidationError("Each remote deck resolution must include a scryfall_id.")
        finish_raw = text_or_none(raw_selection.get("finish"))
        if finish_raw is None:
            raise ValidationError("Each remote deck resolution must include a finish.")
        normalized[source_position] = RemoteDeckResolutionSelection(
            source_position=source_position,
            scryfall_id=scryfall_id,
            finish=normalize_finish(finish_raw),
        )
    return normalized


def _build_remote_resolution_issue(
    kind: str,
    card: RemoteDeckCard,
    *,
    options: list[Any],
) -> RemoteDeckResolutionIssue:
    return RemoteDeckResolutionIssue(
        kind=kind,
        source_position=card.source_position,
        section=card.section,
        requested=_build_remote_requested_card(card),
        options=options,
    )


def _probe_remote_card_resolution(
    connection: sqlite3.Connection,
    *,
    card: RemoteDeckCard,
    default_inventory: str | None,
) -> tuple[PendingImportRow | None, RemoteDeckResolutionIssue | None]:
    if card.scryfall_id is not None:
        resolve_card_row(
            connection,
            scryfall_id=card.scryfall_id,
            oracle_id=None,
            tcgplayer_product_id=None,
            name=None,
            set_code=None,
            collector_number=None,
            lang=None,
            finish=card.finish,
        )
        return _build_pending_remote_row(
            card,
            default_inventory=default_inventory,
            printing_selection_mode="explicit",
        ), None

    if text_or_none(card.name) is None:
        raise ValidationError("Remote deck import requires either a printing id or a card name.")

    if text_or_none(card.set_code) is None and text_or_none(card.collector_number) is None:
        candidate_rows = list_default_card_name_candidate_rows(
            connection,
            name=card.name or "",
            lang=None,
            finish=card.finish,
        )
        oracle_ids = sorted({str(row["oracle_id"]) for row in candidate_rows})
        if len(oracle_ids) > 1:
            options: list[Any] = []
            for oracle_id in oracle_ids:
                resolved_card = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id=oracle_id,
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    finish=card.finish,
                )
                row_options, _ = build_resolution_options_for_catalog_row(
                    resolved_card,
                    requested_finish=card.finish,
                )
                options.extend(row_options)
            return None, _build_remote_resolution_issue("ambiguous_card_name", card, options=options)

        resolved_card = resolve_default_card_row_for_name(
            connection,
            name=card.name or "",
            lang=None,
            finish=card.finish,
        )
        return _build_pending_remote_row(
            _remote_card_with_resolved_printing(
                card,
                scryfall_id=str(resolved_card["scryfall_id"]),
            ),
            default_inventory=default_inventory,
            printing_selection_mode=determine_printing_selection_mode(
                connection,
                scryfall_id=None,
                oracle_id=None,
                tcgplayer_product_id=None,
                name=card.name or "",
                set_code=None,
                set_name=None,
                collector_number=None,
                lang=None,
                finish=card.finish,
            ),
        ), None

    candidate_rows = list_printing_candidate_rows(
        connection,
        name=card.name or "",
        set_code=card.set_code,
        set_name=None,
        collector_number=card.collector_number,
        lang=None,
        finish=card.finish,
    )
    if len(candidate_rows) > 1:
        options: list[Any] = []
        for row in candidate_rows:
            row_options, _ = build_resolution_options_for_catalog_row(
                row,
                requested_finish=card.finish,
            )
            options.extend(row_options)
        return None, _build_remote_resolution_issue("ambiguous_printing", card, options=options)

    return _build_pending_remote_row(
        _remote_card_with_resolved_printing(
            card,
            scryfall_id=str(candidate_rows[0]["scryfall_id"]),
        ),
        default_inventory=default_inventory,
        printing_selection_mode="explicit",
    ), None


def _build_pending_remote_row_from_selection(
    connection: sqlite3.Connection,
    *,
    card: RemoteDeckCard,
    default_inventory: str | None,
    selection: RemoteDeckResolutionSelection,
) -> PendingImportRow:
    pending_row, resolution_issue = _probe_remote_card_resolution(
        connection,
        card=card,
        default_inventory=default_inventory,
    )
    if resolution_issue is None:
        raise ValidationError(f"Remote deck card {card.source_position} does not require an explicit resolution.")

    valid_options = {
        (option.scryfall_id, option.finish)
        for option in resolution_issue.options
    }
    if (selection.scryfall_id, selection.finish) not in valid_options:
        raise ValidationError(
            f"Remote deck card {card.source_position} resolution does not match any suggested option.",
            details={"resolution_issue": serialize_response(resolution_issue)},
        )

    resolve_card_row(
        connection,
        scryfall_id=selection.scryfall_id,
        oracle_id=None,
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=None,
        finish=selection.finish,
    )
    return _build_pending_remote_row(
        _remote_card_with_resolved_printing(
            card,
            scryfall_id=selection.scryfall_id,
            finish=selection.finish,
        ),
        default_inventory=default_inventory,
        printing_selection_mode="explicit",
    )


def _plan_remote_deck_import(
    prepared_db_path: str | Path,
    *,
    source_url: str,
    source_snapshot_token: str | None,
    snapshot_signing_secret: str | None,
    resolutions: list[Mapping[str, Any]] | None,
    inventory_validator: InventoryValidator | None,
    default_inventory: str,
) -> PlannedRemoteDeckImport:
    with connect(prepared_db_path) as connection:
        if inventory_validator is not None:
            inventory_validator(connection, default_inventory)
        get_inventory_row(connection, default_inventory)

    source, snapshot_token = _load_remote_source_for_import(
        source_url,
        source_snapshot_token=source_snapshot_token,
        snapshot_signing_secret=snapshot_signing_secret,
    )
    requested_card_quantity = sum(card.quantity for card in source.cards)
    selection_map = _normalize_remote_resolution_selections(resolutions)
    pending_rows: list[PendingImportRow] = []
    resolution_issues: list[RemoteDeckResolutionIssue] = []

    with connect(prepared_db_path) as connection:
        for card in source.cards:
            selection = selection_map.pop(card.source_position, None)
            if selection is not None:
                pending_rows.append(
                    _build_pending_remote_row_from_selection(
                        connection,
                        card=card,
                        default_inventory=default_inventory,
                        selection=selection,
                    )
                )
                continue

            pending_row, resolution_issue = _probe_remote_card_resolution(
                connection,
                card=card,
                default_inventory=default_inventory,
            )
            if resolution_issue is not None:
                resolution_issues.append(resolution_issue)
                continue
            if pending_row is None:
                raise AssertionError("Remote deck probe returned neither a pending row nor a resolution issue.")
            pending_rows.append(pending_row)

    if selection_map:
        unknown_positions = ", ".join(str(position) for position in sorted(selection_map))
        raise ValidationError(f"remote deck resolutions reference unknown source positions: {unknown_positions}.")

    return PlannedRemoteDeckImport(
        source=source,
        rows_seen=len(source.cards),
        requested_card_quantity=requested_card_quantity,
        source_snapshot_token=snapshot_token,
        pending_rows=pending_rows,
        resolution_issues=resolution_issues,
    )


def import_deck_url(
    db_path: str | Path,
    *,
    source_url: str,
    default_inventory: str | None,
    dry_run: bool = False,
    source_snapshot_token: str | None = None,
    snapshot_signing_secret: str | None = None,
    resolutions: list[Mapping[str, Any]] | None = None,
    before_write: Callable[[], Any] | None = None,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
    schema_policy: SchemaPreparationPolicy = "initialize_if_needed",
) -> dict[str, Any]:
    logger.info(
        "remote_deck_import_start source_url=%s default_inventory=%s dry_run=%s",
        source_url,
        default_inventory,
        dry_run,
    )
    inventory_slug = text_or_none(default_inventory)
    if inventory_slug is None:
        raise ValidationError("default_inventory is required for deck URL imports.")
    prepared_db_path = prepare_database(
        db_path,
        schema_policy=schema_policy,
    )
    plan = _plan_remote_deck_import(
        prepared_db_path,
        source_url=source_url,
        source_snapshot_token=source_snapshot_token,
        snapshot_signing_secret=snapshot_signing_secret,
        resolutions=resolutions,
        inventory_validator=inventory_validator,
        default_inventory=inventory_slug,
    )
    if plan.resolution_issues and not dry_run:
        raise ValidationError(
            "Unresolved remote deck import ambiguities remain.",
            details={
                "resolution_issues": serialize_response(plan.resolution_issues),
                "source_snapshot_token": plan.source_snapshot_token,
            },
        )
    imported_rows = _import_pending_rows(
        prepared_db_path,
        pending_rows=plan.pending_rows,
        dry_run=dry_run,
        before_write=before_write,
        allow_inventory_auto_create=False,
        inventory_validator=inventory_validator,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    logger.info(
        "remote_deck_import_complete provider=%s source_url=%s default_inventory=%s dry_run=%s rows_seen=%s rows_written=%s",
        plan.source.provider,
        plan.source.source_url,
        default_inventory,
        dry_run,
        plan.rows_seen,
        len(imported_rows),
    )
    return {
        "source_url": plan.source.source_url,
        "provider": plan.source.provider,
        "deck_name": plan.source.deck_name,
        "default_inventory": default_inventory,
        "rows_seen": plan.rows_seen,
        "rows_written": len(imported_rows),
        "ready_to_commit": not plan.resolution_issues,
        "source_snapshot_token": plan.source_snapshot_token,
        "summary": build_resolvable_deck_import_summary(
            imported_rows,
            requested_card_quantity=plan.requested_card_quantity,
        ),
        "resolution_issues": serialize_response(plan.resolution_issues),
        "dry_run": dry_run,
        "imported_rows": imported_rows,
    }
