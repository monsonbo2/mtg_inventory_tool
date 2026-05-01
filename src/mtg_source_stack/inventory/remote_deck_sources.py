"""Remote deck source transport and snapshot helpers."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import socket
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..errors import MtgStackError, NotFoundError, ValidationError
from .normalize import normalize_finish, text_or_none

_ARCHIDEKT_HOSTS = {"archidekt.com", "www.archidekt.com"}
_AETHERHUB_HOSTS = {"aetherhub.com", "www.aetherhub.com"}
_MANABOX_HOSTS = {"manabox.app", "www.manabox.app"}
_MOXFIELD_HOSTS = {"moxfield.com", "www.moxfield.com"}
_MTGGOLDFISH_HOSTS = {"mtggoldfish.com", "www.mtggoldfish.com"}
_MTGTOP8_HOSTS = {"mtgtop8.com", "www.mtgtop8.com"}
_TAPPEDOUT_HOSTS = {"tappedout.net", "www.tappedout.net"}
_SUPPORTED_REMOTE_DECK_PROVIDERS_TEXT = (
    "Archidekt, AetherHub, ManaBox, Moxfield, MTGGoldfish, MTGTop8, and TappedOut"
)
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
