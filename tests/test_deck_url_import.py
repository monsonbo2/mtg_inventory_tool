"""Focused tests for remote deck URL import behavior."""

from __future__ import annotations

import base64
from html import escape
from io import BytesIO
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.errors import ValidationError
from mtg_source_stack.inventory.deck_url_import import (
    PlannedRemoteDeckImport,
    RemoteDeckCard,
    RemoteDeckSource,
    _RemoteDeckSourceError,
    _aetherhub_deck_slug_from_url,
    _archidekt_deck_id_from_url,
    _fetch_text,
    _extract_mtggoldfish_download_id,
    _manabox_deck_id_from_url,
    _mtggoldfish_deck_id_from_url,
    _moxfield_public_id_from_url,
    _remote_source_from_aetherhub_page,
    _remote_source_from_manabox_page,
    _remote_source_from_tappedout_page,
    _remote_source_from_mtgtop8_export,
    _tappedout_deck_slug_from_url,
    _mtgtop8_dec_export_url_from_url,
    _remote_source_from_archidekt_payload,
    _remote_source_from_mtggoldfish_downloads,
    _remote_source_from_moxfield_payload,
    fetch_remote_deck_source,
    import_deck_url,
)
from mtg_source_stack.inventory.service import create_inventory


class DeckUrlImportTest(unittest.TestCase):
    class _FakeUrlopenResponse:
        def __init__(self, payload: bytes, *, final_url: str) -> None:
            self._buffer = BytesIO(payload)
            self._final_url = final_url

        def __enter__(self) -> "DeckUrlImportTest._FakeUrlopenResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            return self._buffer.read(size)

        def geturl(self) -> str:
            return self._final_url

    def test_import_deck_url_defaults_to_initialize_if_needed_schema_policy(self) -> None:
        plan = PlannedRemoteDeckImport(
            source=RemoteDeckSource(
                provider="archidekt",
                source_url="https://archidekt.com/decks/123/test",
                deck_name="Test Deck",
                cards=[],
            ),
            rows_seen=0,
            requested_card_quantity=0,
            source_snapshot_token="snapshot-token",
            pending_rows=[],
            resolution_issues=[],
        )
        prepared_db_path = Path("/tmp/prepared_deck_url_import.db")

        with (
            patch(
                "mtg_source_stack.inventory.deck_url_import.prepare_database",
                return_value=prepared_db_path,
            ) as prepare_database,
            patch(
                "mtg_source_stack.inventory.deck_url_import._plan_remote_deck_import",
                return_value=plan,
            ) as plan_remote_deck_import,
            patch(
                "mtg_source_stack.inventory.deck_url_import._import_pending_rows",
                return_value=[],
            ) as import_pending_rows,
        ):
            result = import_deck_url(
                "collection.db",
                source_url="https://archidekt.com/decks/123/test",
                default_inventory="personal",
            )

        prepare_database.assert_called_once_with(
            "collection.db",
            schema_policy="initialize_if_needed",
        )
        self.assertEqual(prepared_db_path, plan_remote_deck_import.call_args.args[0])
        self.assertEqual(prepared_db_path, import_pending_rows.call_args.args[0])
        self.assertEqual("archidekt", result["provider"])

    def test_import_deck_url_accepts_require_current_schema_policy(self) -> None:
        plan = PlannedRemoteDeckImport(
            source=RemoteDeckSource(
                provider="archidekt",
                source_url="https://archidekt.com/decks/123/test",
                deck_name="Test Deck",
                cards=[],
            ),
            rows_seen=0,
            requested_card_quantity=0,
            source_snapshot_token="snapshot-token",
            pending_rows=[],
            resolution_issues=[],
        )
        prepared_db_path = Path("/tmp/prepared_deck_url_import.db")

        with (
            patch(
                "mtg_source_stack.inventory.deck_url_import.prepare_database",
                return_value=prepared_db_path,
            ) as prepare_database,
            patch(
                "mtg_source_stack.inventory.deck_url_import._plan_remote_deck_import",
                return_value=plan,
            ),
            patch(
                "mtg_source_stack.inventory.deck_url_import._import_pending_rows",
                return_value=[],
            ),
        ):
            import_deck_url(
                "collection.db",
                source_url="https://archidekt.com/decks/123/test",
                default_inventory="personal",
                schema_policy="require_current",
            )

        prepare_database.assert_called_once_with(
            "collection.db",
            schema_policy="require_current",
        )

    def _manabox_page_html(self, deck_payload: dict[str, object]) -> str:
        props = json.dumps({"deck": [0, deck_payload]}, separators=(",", ":"))
        return f'<astro-island component-export="Main" props="{escape(props, quote=True)}"></astro-island>'

    def _insert_card(
        self,
        db_path: Path,
        *,
        scryfall_id: str,
        oracle_id: str,
        name: str,
        collector_number: str,
        finishes_json: str,
    ) -> None:
        with connect(db_path) as connection:
            connection.execute(
                """
                INSERT INTO mtg_cards (
                    scryfall_id,
                    oracle_id,
                    name,
                    set_code,
                    set_name,
                    collector_number,
                    lang,
                    finishes_json
                )
                VALUES (?, ?, ?, 'tst', 'Test Set', ?, 'en', ?)
                """,
                (scryfall_id, oracle_id, name, collector_number, finishes_json),
            )
            connection.commit()

    def test_archidekt_deck_id_from_url_accepts_public_and_api_urls(self) -> None:
        self.assertEqual(
            "12931478",
            _archidekt_deck_id_from_url("https://archidekt.com/decks/12931478/eldrazi_winter"),
        )
        self.assertEqual(
            "12931478",
            _archidekt_deck_id_from_url("https://archidekt.com/api/decks/12931478/"),
        )

    def test_moxfield_public_id_from_url_accepts_public_urls(self) -> None:
        self.assertEqual(
            "qNF3FLXLGUWAird08TxYrw",
            _moxfield_public_id_from_url("https://moxfield.com/decks/qNF3FLXLGUWAird08TxYrw"),
        )
        self.assertEqual(
            "qNF3FLXLGUWAird08TxYrw",
            _moxfield_public_id_from_url("https://www.moxfield.com/decks/qNF3FLXLGUWAird08TxYrw/eldrazi"),
        )

    def test_aetherhub_deck_slug_from_url_accepts_deck_and_metagame_urls(self) -> None:
        self.assertEqual(
            "deck-969058",
            _aetherhub_deck_slug_from_url("https://aetherhub.com/Deck/deck-969058"),
        )
        self.assertEqual(
            "historic-charbelcher-123",
            _aetherhub_deck_slug_from_url(
                "https://www.aetherhub.com/Metagame/Standard-BO1/Deck/historic-charbelcher-123"
            ),
        )

    def test_manabox_deck_id_from_url_accepts_public_urls(self) -> None:
        self.assertEqual(
            "dM1irGrkS9GZqEiOTtnO1Q",
            _manabox_deck_id_from_url("https://manabox.app/decks/dM1irGrkS9GZqEiOTtnO1Q"),
        )
        self.assertEqual(
            "dM1irGrkS9GZqEiOTtnO1Q",
            _manabox_deck_id_from_url("https://www.manabox.app/decks/dM1irGrkS9GZqEiOTtnO1Q/share"),
        )

    def test_mtggoldfish_deck_id_from_url_accepts_direct_and_archetype_urls(self) -> None:
        self.assertEqual(
            "7252087",
            _mtggoldfish_deck_id_from_url("https://www.mtggoldfish.com/deck/7252087#paper"),
        )
        self.assertEqual(
            "7252087",
            _mtggoldfish_deck_id_from_url("https://www.mtggoldfish.com/deck/download/7252087"),
        )

        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_text",
            return_value="""
                <html>
                  <a class="dropdown-item" href="/deck/download/7252087">Text File (Default)</a>
                </html>
            """,
        ):
            self.assertEqual(
                "7252087",
                _mtggoldfish_deck_id_from_url("https://www.mtggoldfish.com/archetype/brawl-sliver-hivelord"),
            )

    def test_mtgtop8_dec_export_url_from_url_accepts_direct_and_event_urls(self) -> None:
        self.assertEqual(
            "https://www.mtgtop8.com/dec?d=749833&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic",
            _mtgtop8_dec_export_url_from_url(
                "https://www.mtgtop8.com/event?d=749833&e=72479&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic"
            ),
        )
        self.assertEqual(
            "https://www.mtgtop8.com/dec?d=749833&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic",
            _mtgtop8_dec_export_url_from_url(
                "https://www.mtgtop8.com/dec?d=749833&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic"
            ),
        )

    def test_mtgtop8_dec_export_url_from_url_discovers_export_link_from_page(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_text",
            return_value='<a href=dec?d=749833&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic>.dec</a>',
        ):
            self.assertEqual(
                "https://www.mtgtop8.com/dec?d=749833&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic",
                _mtgtop8_dec_export_url_from_url("https://www.mtgtop8.com/event?e=72479"),
            )

    def test_tappedout_deck_slug_from_url_accepts_public_urls(self) -> None:
        self.assertEqual(
            "commander-edh-deck",
            _tappedout_deck_slug_from_url("https://tappedout.net/mtg-decks/commander-edh-deck/"),
        )
        self.assertEqual(
            "commander-edh-deck",
            _tappedout_deck_slug_from_url("https://www.tappedout.net/mtg-decks/commander-edh-deck/deckcycle/"),
        )

    def test_extract_mtggoldfish_download_id_requires_download_link(self) -> None:
        self.assertEqual(
            "7252087",
            _extract_mtggoldfish_download_id('<a href="/deck/download/7252087">Download</a>'),
        )

    def test_fetch_text_distinguishes_http_404_and_403(self) -> None:
        url = "https://www.mtggoldfish.com/deck/7171667#paper"

        with patch(
            "mtg_source_stack.inventory.deck_url_import.urlopen",
            side_effect=HTTPError(url, 404, "missing", hdrs=None, fp=None),
        ):
            with self.assertRaises(_RemoteDeckSourceError) as not_found_error:
                _fetch_text(url)

        self.assertEqual("not_found", not_found_error.exception.code)

        with patch(
            "mtg_source_stack.inventory.deck_url_import.urlopen",
            side_effect=HTTPError(url, 403, "blocked", hdrs=None, fp=None),
        ):
            with self.assertRaises(_RemoteDeckSourceError) as blocked_error:
                _fetch_text(url)

        self.assertEqual("private_or_blocked", blocked_error.exception.code)

    def test_fetch_text_rejects_redirect_to_unsupported_host(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import.urlopen",
            return_value=self._FakeUrlopenResponse(
                b"{}",
                final_url="https://example.test/decks/redirected",
            ),
        ):
            with self.assertRaises(_RemoteDeckSourceError) as error:
                _fetch_text("https://archidekt.com/api/decks/123/")

        self.assertEqual("unsupported_provider", error.exception.code)

    def test_fetch_text_rejects_oversized_payload(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import.urlopen",
            return_value=self._FakeUrlopenResponse(
                b"x" * ((2 * 1024 * 1024) + 1),
                final_url="https://archidekt.com/api/decks/123/",
            ),
        ):
            with self.assertRaises(_RemoteDeckSourceError) as error:
                _fetch_text("https://archidekt.com/api/decks/123/")

        self.assertEqual("unexpected_payload", error.exception.code)

    def test_archidekt_payload_maps_sections_and_skips_maybeboard(self) -> None:
        source = _remote_source_from_archidekt_payload(
            "https://archidekt.com/decks/123/test",
            {
                "name": "Remote Deck",
                "categories": [
                    {"name": "Commander", "includedInDeck": True},
                    {"name": "Sideboard", "includedInDeck": True},
                    {"name": "Maybeboard", "includedInDeck": False},
                    {"name": "Ramp", "includedInDeck": True},
                ],
                "cards": [
                    {
                        "categories": ["Commander"],
                        "companion": False,
                        "modifier": "Normal",
                        "quantity": 1,
                        "card": {"uid": "cmd-card"},
                    },
                    {
                        "categories": ["Ramp"],
                        "companion": False,
                        "modifier": "Foil",
                        "quantity": 4,
                        "card": {"uid": "main-card"},
                    },
                    {
                        "categories": ["Maybeboard"],
                        "companion": False,
                        "modifier": "Normal",
                        "quantity": 2,
                        "card": {"uid": "maybe-card"},
                    },
                    {
                        "categories": ["Sideboard"],
                        "companion": False,
                        "modifier": "Etched",
                        "quantity": 1,
                        "card": {"uid": "side-card"},
                    },
                ],
            },
        )

        self.assertEqual("archidekt", source.provider)
        self.assertEqual("Remote Deck", source.deck_name)
        self.assertEqual(
            [
                (1, "commander", 1, "cmd-card", "normal"),
                (2, "mainboard", 4, "main-card", "foil"),
                (4, "sideboard", 1, "side-card", "etched"),
            ],
            [
                (
                    card.source_position,
                    card.section,
                    card.quantity,
                    card.scryfall_id,
                    card.finish,
                )
                for card in source.cards
            ],
        )

    def test_moxfield_payload_maps_supported_sections_and_skips_maybeboard(self) -> None:
        source = _remote_source_from_moxfield_payload(
            "https://moxfield.com/decks/qNF3FLXLGUWAird08TxYrw",
            {
                "name": "Moxfield Deck",
                "commanders": {
                    "cmd-key": {
                        "quantity": 1,
                        "finish": "nonfoil",
                        "card": {"scryfall_id": "cmd-card"},
                    }
                },
                "companions": {
                    "comp-key": {
                        "quantity": 1,
                        "finish": "foil",
                        "card": {"scryfall_id": "comp-card"},
                    }
                },
                "mainboard": {
                    "main-key": {
                        "quantity": 4,
                        "finish": "etched foil",
                        "card": {"scryfall_id": "main-card"},
                    }
                },
                "sideboard": {
                    "side-key": {
                        "quantity": 2,
                        "isFoil": True,
                        "card": {
                            "scryfall_id": "side-card",
                            "defaultFinish": "nonfoil",
                        },
                    }
                },
                "signatureSpells": {
                    "sig-key": {
                        "quantity": 1,
                        "finish": "normal",
                        "card": {"scryfall_id": "sig-card"},
                    }
                },
                "maybeboard": {
                    "maybe-key": {
                        "quantity": 9,
                        "finish": "normal",
                        "card": {"scryfall_id": "maybe-card"},
                    }
                },
                "tokens": [
                    {"scryfall_id": "token-card"},
                ],
            },
        )

        self.assertEqual("moxfield", source.provider)
        self.assertEqual("Moxfield Deck", source.deck_name)
        self.assertEqual(
            [
                (1, "commander", 1, "cmd-card", "normal"),
                (2, "companion", 1, "comp-card", "foil"),
                (3, "signature-spell", 1, "sig-card", "normal"),
                (4, "mainboard", 4, "main-card", "etched"),
                (5, "sideboard", 2, "side-card", "foil"),
            ],
            [
                (
                    card.source_position,
                    card.section,
                    card.quantity,
                    card.scryfall_id,
                    card.finish,
                )
                for card in source.cards
            ],
        )

    def test_manabox_page_maps_structured_cards_sections_finishes_and_skips_maybeboard(self) -> None:
        source = _remote_source_from_manabox_page(
            "https://manabox.app/decks/vaZZ5birTU6iDWgcaNgEcg",
            page_html=self._manabox_page_html(
                {
                    "name": [0, "ManaBox Deck"],
                    "cards": [
                        1,
                        [
                            [
                                0,
                                {
                                    "name": [0, "Arabella, Abandoned Doll"],
                                    "quantity": [0, 1],
                                    "boardCategory": [0, 0],
                                    "variant": [0, "Foil"],
                                    "setId": [0, "dsk"],
                                    "collectorNumber": [0, "208"],
                                },
                            ],
                            [
                                0,
                                {
                                    "name": [0, "Lightning Bolt"],
                                    "quantity": [0, 4],
                                    "boardCategory": [0, 3],
                                    "variant": [0, "Normal"],
                                    "setId": [0, "lea"],
                                    "collectorNumber": [0, "161"],
                                },
                            ],
                            [
                                0,
                                {
                                    "name": [0, "Jegantha, the Wellspring"],
                                    "quantity": [0, 1],
                                    "boardCategory": [0, 1],
                                    "variant": [0, "Normal"],
                                    "setId": [0, "iko"],
                                    "collectorNumber": [0, "222"],
                                },
                            ],
                            [
                                0,
                                {
                                    "name": [0, "Disenchant"],
                                    "quantity": [0, 2],
                                    "boardCategory": [0, 4],
                                    "variant": [0, "Normal"],
                                    "setId": [0, "30a"],
                                    "collectorNumber": [0, "33"],
                                },
                            ],
                            [
                                0,
                                {
                                    "name": [0, "Maybe Card"],
                                    "quantity": [0, 7],
                                    "boardCategory": [0, 2],
                                    "variant": [0, "Normal"],
                                    "setId": [0, "mh2"],
                                    "collectorNumber": [0, "999"],
                                },
                            ],
                        ],
                    ],
                }
            ),
        )

        self.assertEqual("manabox", source.provider)
        self.assertEqual("ManaBox Deck", source.deck_name)
        self.assertEqual(
            [
                (1, "commander", 1, "Arabella, Abandoned Doll", "DSK", "208", "foil"),
                (2, "mainboard", 4, "Lightning Bolt", "LEA", "161", "normal"),
                (3, "companion", 1, "Jegantha, the Wellspring", "IKO", "222", "normal"),
                (4, "sideboard", 2, "Disenchant", "30A", "33", "normal"),
            ],
            [
                (
                    card.source_position,
                    card.section,
                    card.quantity,
                    card.name,
                    card.set_code,
                    card.collector_number,
                    card.finish,
                )
                for card in source.cards
            ],
        )

    def test_mtggoldfish_downloads_map_sections_exact_printing_hints_and_finishes(self) -> None:
        source = _remote_source_from_mtggoldfish_downloads(
            "https://www.mtggoldfish.com/deck/7171667",
            arena_page_html="""
                <textarea class='copy-paste-box'>About
                Name Hidden Strings

                Deck
                4 Artist's Talent
                4 Hidden Strings

                Sideboard
                2 Chandra's Defeat
                1 Hidden Strings
                </textarea>
            """,
            exact_download_text="""
                4 Artist's Talent [BLB] (F)
                4 Hidden Strings [DGM]

                2 Chandra's Defeat [AKR]
                1 Hidden Strings [DGM] (F)
            """,
        )

        self.assertEqual("mtggoldfish", source.provider)
        self.assertEqual("Hidden Strings", source.deck_name)
        self.assertEqual(
            [
                (1, "mainboard", 4, None, "Artist's Talent", "BLB", None, "foil"),
                (2, "mainboard", 4, None, "Hidden Strings", "DGM", None, "normal"),
                (3, "sideboard", 2, None, "Chandra's Defeat", "AKR", None, "normal"),
                (4, "sideboard", 1, None, "Hidden Strings", "DGM", None, "foil"),
            ],
            [
                (
                    card.source_position,
                    card.section,
                    card.quantity,
                    card.scryfall_id,
                    card.name,
                    card.set_code,
                    card.collector_number,
                    card.finish,
                )
                for card in source.cards
            ],
        )

    def test_mtggoldfish_downloads_infer_commander_and_collector_number(self) -> None:
        source = _remote_source_from_mtggoldfish_downloads(
            "https://www.mtggoldfish.com/deck/7252087",
            arena_page_html="""
                <textarea class='copy-paste-box'>About
                Name Slivers

                Commander
                1 Sliver Hivelord

                Deck
                6 Forest
                1 The First Sliver
                </textarea>
            """,
            exact_download_text="""
                6 Forest <254> [THB]
                1 Sliver Hivelord [M15]
                1 The First Sliver <retro> [MH2] (FE)
            """,
        )

        self.assertEqual(
            [
                ("mainboard", "Forest", "THB", "254", "normal"),
                ("commander", "Sliver Hivelord", "M15", None, "normal"),
                ("mainboard", "The First Sliver", "MH2", None, "etched"),
            ],
            [
                (
                    card.section,
                    card.name,
                    card.set_code,
                    card.collector_number,
                    card.finish,
                )
                for card in source.cards
            ],
        )

    def test_mtgtop8_export_maps_sections_and_set_codes(self) -> None:
        source = _remote_source_from_mtgtop8_export(
            "https://www.mtgtop8.com/event?d=749833&e=72479&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic",
            export_text="""
                // Deck file created with mtgtop8.com
                // NAME : Optimal Dreadnought Decklist
                // CREATOR : Ondrej_Kedrovic
                4 [NE] Accumulated Knowledge
                2 [ON] Chain of Vapor
                SB:  1 [UD] Powder Keg
            """,
        )

        self.assertEqual("mtgtop8", source.provider)
        self.assertEqual("Optimal Dreadnought Decklist", source.deck_name)
        self.assertEqual(
            [
                (1, "mainboard", 4, "Accumulated Knowledge", "NE", "normal"),
                (2, "mainboard", 2, "Chain of Vapor", "ON", "normal"),
                (3, "sideboard", 1, "Powder Keg", "UD", "normal"),
            ],
            [
                (
                    card.source_position,
                    card.section,
                    card.quantity,
                    card.name,
                    card.set_code,
                    card.finish,
                )
                for card in source.cards
            ],
        )

    def test_tappedout_page_uses_mtga_export_with_exact_printing_hints(self) -> None:
        source = _remote_source_from_tappedout_page(
            "https://tappedout.net/mtg-decks/commander-edh-deck/",
            page_html="""
                <textarea id="mtga-textarea">About
                Name Commander EDH deck

                Commander
                1x Sisay, Weatherlight Captain (MH1) 29

                Deck
                1x Aclazotz, Deepest Betrayal (LCI) 88
                9x Snow-Covered Forest (KHM) 284
                </textarea>
            """,
        )

        self.assertEqual("tappedout", source.provider)
        self.assertEqual("Commander EDH deck", source.deck_name)
        self.assertEqual(
            [
                (2, "commander", 1, "Sisay, Weatherlight Captain", "MH1", "29", "normal"),
                (5, "mainboard", 1, "Aclazotz, Deepest Betrayal", "LCI", "88", "normal"),
                (6, "mainboard", 9, "Snow-Covered Forest", "KHM", "284", "normal"),
            ],
            [
                (
                    card.source_position,
                    card.section,
                    card.quantity,
                    card.name,
                    card.set_code,
                    card.collector_number,
                    card.finish,
                )
                for card in source.cards
            ],
        )

    def test_aetherhub_page_maps_visible_sections_and_name_only_rows(self) -> None:
        source = _remote_source_from_aetherhub_page(
            "https://aetherhub.com/Deck/narci-binay",
            page_html="""
                <html>
                  <head>
                    <meta property="og:title" content="Commander - Precon" />
                  </head>
                  <body>
                    <section>
                      <h5>Commander 1 cards (1 distinct)</h5>
                      <div>1 <span>Gylwain, Casting Director</span> | | | $0.92</div>
                    </section>
                    <section>
                      <h5>Main 99 cards (72 distinct)</h5>
                      <div>Lands - 39</div>
                      <div>1 Ajani's Chosen | | | $0.47</div>
                      <div>1 Archon of Sun's Grace | | | $0.80</div>
                    </section>
                    <section>
                      <h5>Side 2 cards (2 distinct)</h5>
                      <div>1 Return to Dust | | | $0.25</div>
                      <div>1 Generous Gift | | | $0.44</div>
                    </section>
                    <section>
                      <h5>Commander 1 cards (1 distinct)</h5>
                      <div>1 Gylwain, Casting Director | | | $0.92</div>
                    </section>
                  </body>
                </html>
            """,
        )

        self.assertEqual("aetherhub", source.provider)
        self.assertEqual("Commander - Precon", source.deck_name)
        self.assertEqual(
            [
                (1, "commander", 1, None, "Gylwain, Casting Director", "normal"),
                (2, "mainboard", 1, None, "Ajani's Chosen", "normal"),
                (3, "mainboard", 1, None, "Archon of Sun's Grace", "normal"),
                (4, "sideboard", 1, None, "Return to Dust", "normal"),
                (5, "sideboard", 1, None, "Generous Gift", "normal"),
            ],
            [
                (
                    card.source_position,
                    card.section,
                    card.quantity,
                    card.scryfall_id,
                    card.name,
                    card.finish,
                )
                for card in source.cards
            ],
        )

    def test_fetch_remote_deck_source_uses_moxfield_api_payload(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_json",
            return_value={
                "name": "Fetched Moxfield Deck",
                "mainboard": {
                    "main-key": {
                        "quantity": 1,
                        "finish": "normal",
                        "card": {"scryfall_id": "main-card"},
                    }
                },
            },
        ) as fetch_json:
            source = fetch_remote_deck_source("https://moxfield.com/decks/qNF3FLXLGUWAird08TxYrw")

        self.assertEqual("moxfield", source.provider)
        self.assertEqual("Fetched Moxfield Deck", source.deck_name)
        self.assertEqual(1, len(source.cards))
        fetch_json.assert_called_once_with("https://api2.moxfield.com/v2/decks/all/qNF3FLXLGUWAird08TxYrw")

    def test_fetch_remote_deck_source_surfaces_moxfield_paste_fallback_on_blocked_fetch(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_json",
            side_effect=_RemoteDeckSourceError(
                code="private_or_blocked",
                message="blocked",
            ),
        ):
            with self.assertRaisesRegex(
                ValidationError,
                "paste the deck text into /imports/decklist",
            ):
                fetch_remote_deck_source("https://moxfield.com/decks/qNF3FLXLGUWAird08TxYrw")

    def test_fetch_remote_deck_source_surfaces_provider_specific_timeout(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_text",
            side_effect=_RemoteDeckSourceError(
                code="timeout",
                message="timed out",
            ),
        ):
            with self.assertRaisesRegex(
                ValidationError,
                "AetherHub deck URL fetch timed out",
            ):
                fetch_remote_deck_source("https://aetherhub.com/Deck/deck-969058")

    def test_fetch_remote_deck_source_surfaces_provider_parse_drift(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_json",
            return_value={},
        ):
            with self.assertRaisesRegex(
                ValidationError,
                "Archidekt deck URL returned an unexpected payload shape",
            ):
                fetch_remote_deck_source("https://archidekt.com/decks/123/test")

    def test_fetch_remote_deck_source_uses_mtggoldfish_downloads(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_text",
            side_effect=[
                """
                    <textarea class='copy-paste-box'>About
                    Name Hidden Strings

                    Deck
                    4 Artist's Talent
                    </textarea>
                """,
                "4 Artist's Talent [BLB] (F)\n",
            ],
        ) as fetch_text:
            source = fetch_remote_deck_source("https://www.mtggoldfish.com/deck/7171667#paper")

        self.assertEqual("mtggoldfish", source.provider)
        self.assertEqual("Hidden Strings", source.deck_name)
        self.assertEqual(1, len(source.cards))
        self.assertEqual(
            [
                ("https://www.mtggoldfish.com/deck/arena_download/7171667",),
                ("https://www.mtggoldfish.com/deck/download/7171667?output=mtggoldfish&type=tabletop",),
            ],
            [call.args for call in fetch_text.call_args_list],
        )

    def test_fetch_remote_deck_source_uses_aetherhub_deck_page(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_text",
            return_value="""
                <html>
                  <meta property="og:title" content="Commander - Precon" />
                  <h5>Commander 1 cards (1 distinct)</h5>
                  <div>1 Gylwain, Casting Director | | | $0.92</div>
                </html>
            """,
        ) as fetch_text:
            source = fetch_remote_deck_source("https://www.aetherhub.com/Metagame/Standard-BO1/Deck/narci-binay")

        self.assertEqual("aetherhub", source.provider)
        self.assertEqual("Commander - Precon", source.deck_name)
        self.assertEqual(1, len(source.cards))
        fetch_text.assert_called_once_with("https://aetherhub.com/Deck/narci-binay")

    def test_fetch_remote_deck_source_uses_manabox_shared_page(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_text",
            return_value=self._manabox_page_html(
                {
                    "name": [0, "ManaBox Deck"],
                    "cards": [
                        1,
                        [
                            [
                                0,
                                {
                                    "name": [0, "Arabella, Abandoned Doll"],
                                    "quantity": [0, 1],
                                    "boardCategory": [0, 0],
                                    "variant": [0, "Foil"],
                                    "setId": [0, "dsk"],
                                    "collectorNumber": [0, "208"],
                                },
                            ]
                        ],
                    ],
                }
            ),
        ) as fetch_text:
            source = fetch_remote_deck_source("https://manabox.app/decks/vaZZ5birTU6iDWgcaNgEcg")

        self.assertEqual("manabox", source.provider)
        self.assertEqual("ManaBox Deck", source.deck_name)
        self.assertEqual(1, len(source.cards))
        fetch_text.assert_called_once_with("https://manabox.app/decks/vaZZ5birTU6iDWgcaNgEcg")

    def test_fetch_remote_deck_source_uses_mtgtop8_dec_export(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_text",
            return_value="""
                // Deck file created with mtgtop8.com
                // NAME : Optimal Dreadnought Decklist
                4 [NE] Accumulated Knowledge
            """,
        ) as fetch_text:
            source = fetch_remote_deck_source(
                "https://www.mtgtop8.com/event?d=749833&e=72479&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic"
            )

        self.assertEqual("mtgtop8", source.provider)
        self.assertEqual("Optimal Dreadnought Decklist", source.deck_name)
        self.assertEqual(1, len(source.cards))
        fetch_text.assert_called_once_with(
            "https://www.mtgtop8.com/dec?d=749833&f=Premodern_Optimal_Dreadnought_Decklist_by_Ondrej_Kedrovic"
        )

    def test_fetch_remote_deck_source_uses_tappedout_page_export(self) -> None:
        with patch(
            "mtg_source_stack.inventory.deck_url_import._fetch_text",
            return_value="""
                <textarea id="mtga-textarea">About
                Name Commander EDH deck

                Commander
                1x Sisay, Weatherlight Captain (MH1) 29
                </textarea>
            """,
        ) as fetch_text:
            source = fetch_remote_deck_source("https://tappedout.net/mtg-decks/commander-edh-deck/deckcycle/")

        self.assertEqual("tappedout", source.provider)
        self.assertEqual("Commander EDH deck", source.deck_name)
        self.assertEqual(1, len(source.cards))
        fetch_text.assert_called_once_with("https://tappedout.net/mtg-decks/commander-edh-deck/")

    def test_import_deck_url_supports_preview_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="cmd-card",
                oracle_id="remote-oracle-1",
                name="Commander Card",
                collector_number="1",
                finishes_json='["normal"]',
            )
            self._insert_card(
                db_path,
                scryfall_id="main-card",
                oracle_id="remote-oracle-2",
                name="Main Card",
                collector_number="2",
                finishes_json='["normal","foil"]',
            )
            self._insert_card(
                db_path,
                scryfall_id="side-card",
                oracle_id="remote-oracle-3",
                name="Side Card",
                collector_number="3",
                finishes_json='["etched"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="archidekt",
                source_url="https://archidekt.com/decks/123/test",
                deck_name="Remote Deck",
                cards=[
                    RemoteDeckCard(1, 1, "commander", "cmd-card", "normal"),
                    RemoteDeckCard(2, 4, "mainboard", "main-card", "foil"),
                    RemoteDeckCard(3, 1, "sideboard", "side-card", "etched"),
                ],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                preview = import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/123/test",
                    default_inventory="personal",
                    dry_run=True,
                )
                self.assertTrue(preview["dry_run"])
                self.assertEqual("archidekt", preview["provider"])
                self.assertEqual("Remote Deck", preview["deck_name"])
                self.assertEqual(3, preview["rows_seen"])
                self.assertEqual(3, preview["rows_written"])
                self.assertTrue(preview["ready_to_commit"])
                self.assertIsInstance(preview["source_snapshot_token"], str)
                self.assertEqual([], preview["resolution_issues"])
                self.assertEqual(6, preview["summary"]["requested_card_quantity"])
                self.assertEqual(0, preview["summary"]["unresolved_card_quantity"])
                self.assertEqual(1, preview["imported_rows"][0]["source_position"])
                self.assertEqual("commander", preview["imported_rows"][0]["section"])
                self.assertEqual("foil", preview["imported_rows"][1]["finish"])
                self.assertEqual("etched", preview["imported_rows"][2]["finish"])
                self.assertEqual("explicit", preview["imported_rows"][0]["printing_selection_mode"])

                with connect(db_path) as connection:
                    self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0])

                committed = import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/123/test",
                    default_inventory="personal",
                    dry_run=False,
                    source_snapshot_token=preview["source_snapshot_token"],
                )

            self.assertFalse(committed["dry_run"])
            self.assertEqual(3, committed["rows_written"])
            self.assertTrue(committed["ready_to_commit"])
            self.assertEqual([], committed["resolution_issues"])

            with connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT scryfall_id, quantity, finish, printing_selection_mode FROM inventory_items ORDER BY scryfall_id"
                ).fetchall()
            self.assertEqual(
                [
                    ("cmd-card", 1, "normal", "explicit"),
                    ("main-card", 4, "foil", "explicit"),
                    ("side-card", 1, "etched", "explicit"),
                ],
                [
                    (
                        row["scryfall_id"],
                        row["quantity"],
                        row["finish"],
                        row["printing_selection_mode"],
                    )
                    for row in rows
                ],
            )

    def test_import_deck_url_marks_name_only_default_rows_as_defaulted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="remote-default-mainstream-en",
                oracle_id="remote-default-oracle",
                name="Remote Defaulted Card",
                collector_number="1",
                finishes_json='["normal"]',
            )
            with connect(db_path) as connection:
                connection.execute(
                    """
                    UPDATE mtg_cards
                    SET set_code = 'bro',
                        set_name = 'The Brothers'' War',
                        released_at = '2023-11-18',
                        set_type = 'expansion',
                        booster = 1,
                        promo_types_json = '[]'
                    WHERE scryfall_id = 'remote-default-mainstream-en'
                    """
                )
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        lang,
                        released_at,
                        finishes_json,
                        set_type,
                        booster,
                        promo_types_json
                    )
                    VALUES (
                        'remote-default-promo-en',
                        'remote-default-oracle',
                        'Remote Defaulted Card',
                        'pneo',
                        'Kamigawa: Neon Dynasty Promos',
                        '2',
                        'en',
                        '2024-03-01',
                        '["normal"]',
                        'expansion',
                        0,
                        '["promo_pack"]'
                    )
                    """
                )
                connection.commit()
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="archidekt",
                source_url="https://archidekt.com/decks/123/test",
                deck_name="Remote Defaulted Deck",
                cards=[
                    RemoteDeckCard(
                        1,
                        2,
                        "mainboard",
                        None,
                        "normal",
                        name="Remote Defaulted Card",
                    )
                ],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                committed = import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/123/test",
                    default_inventory="personal",
                    dry_run=False,
                )

            self.assertEqual("remote-default-mainstream-en", committed["imported_rows"][0]["scryfall_id"])
            self.assertEqual("defaulted", committed["imported_rows"][0]["printing_selection_mode"])

            with connect(db_path) as connection:
                row = connection.execute(
                    "SELECT scryfall_id, printing_selection_mode FROM inventory_items"
                ).fetchone()

            self.assertEqual("remote-default-mainstream-en", row["scryfall_id"])
            self.assertEqual("defaulted", row["printing_selection_mode"])

    def test_import_deck_url_supports_exact_printing_name_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="cmd-card",
                oracle_id="remote-oracle-1",
                name="Commander Card",
                collector_number="1",
                finishes_json='["normal"]',
            )
            self._insert_card(
                db_path,
                scryfall_id="main-card",
                oracle_id="remote-oracle-2",
                name="Main Card",
                collector_number="2",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="tappedout",
                source_url="https://tappedout.net/mtg-decks/commander-edh-deck/",
                deck_name="TappedOut Deck",
                cards=[
                    RemoteDeckCard(
                        2,
                        1,
                        "commander",
                        None,
                        "normal",
                        name="Commander Card",
                        set_code="TST",
                        collector_number="1",
                    ),
                    RemoteDeckCard(
                        5,
                        2,
                        "mainboard",
                        None,
                        "normal",
                        name="Main Card",
                        set_code="TST",
                        collector_number="2",
                    ),
                ],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                preview = import_deck_url(
                    db_path,
                    source_url="https://tappedout.net/mtg-decks/commander-edh-deck/",
                    default_inventory="personal",
                    dry_run=True,
                )
                self.assertEqual("tappedout", preview["provider"])
                self.assertEqual(2, preview["rows_written"])
                self.assertEqual("Commander Card", preview["imported_rows"][0]["card_name"])

                committed = import_deck_url(
                    db_path,
                    source_url="https://tappedout.net/mtg-decks/commander-edh-deck/",
                    default_inventory="personal",
                    dry_run=False,
                )

            self.assertFalse(committed["dry_run"])
            self.assertEqual(2, committed["rows_written"])
            with connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT scryfall_id, quantity FROM inventory_items ORDER BY scryfall_id"
                ).fetchall()
            self.assertEqual(
                [("cmd-card", 1), ("main-card", 2)],
                [(row["scryfall_id"], row["quantity"]) for row in rows],
            )

    def test_import_deck_url_supports_default_name_resolution_for_name_only_provider_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="cmd-card",
                oracle_id="oracle-cmd",
                name="Commander Card",
                collector_number="1",
                finishes_json='["normal"]',
            )
            self._insert_card(
                db_path,
                scryfall_id="main-card-default",
                oracle_id="oracle-main",
                name="Main Card",
                collector_number="2",
                finishes_json='["normal"]',
            )
            self._insert_card(
                db_path,
                scryfall_id="main-card-promo",
                oracle_id="oracle-main",
                name="Main Card",
                collector_number="99",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="aetherhub",
                source_url="https://aetherhub.com/Deck/narci-binay",
                deck_name="Commander - Precon",
                cards=[
                    RemoteDeckCard(
                        1,
                        1,
                        "commander",
                        None,
                        "normal",
                        name="Commander Card",
                    ),
                    RemoteDeckCard(
                        2,
                        2,
                        "mainboard",
                        None,
                        "normal",
                        name="Main Card",
                    ),
                ],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                preview = import_deck_url(
                    db_path,
                    source_url="https://aetherhub.com/Deck/narci-binay",
                    default_inventory="personal",
                    dry_run=True,
                )
                self.assertEqual("aetherhub", preview["provider"])
                self.assertEqual(2, preview["rows_written"])
                self.assertEqual("Commander Card", preview["imported_rows"][0]["card_name"])
                self.assertEqual("Main Card", preview["imported_rows"][1]["card_name"])

                committed = import_deck_url(
                    db_path,
                    source_url="https://aetherhub.com/Deck/narci-binay",
                    default_inventory="personal",
                    dry_run=False,
                )

            self.assertFalse(committed["dry_run"])
            self.assertEqual(2, committed["rows_written"])
            with connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT scryfall_id, quantity FROM inventory_items ORDER BY scryfall_id"
                ).fetchall()
            self.assertEqual(
                [("cmd-card", 1), ("main-card-default", 2)],
                [(row["scryfall_id"], row["quantity"]) for row in rows],
            )

    def test_import_deck_url_returns_resolution_issues_and_accepts_snapshot_resolutions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="remote-ambiguous-main",
                oracle_id="remote-ambiguous-main-oracle",
                name="Remote Ambiguous Card",
                collector_number="1",
                finishes_json='["normal"]',
            )
            self._insert_card(
                db_path,
                scryfall_id="remote-ambiguous-other",
                oracle_id="remote-ambiguous-other-oracle",
                name="Remote Ambiguous Card",
                collector_number="2",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="aetherhub",
                source_url="https://aetherhub.com/Deck/test-ambiguous",
                deck_name="Ambiguous Remote Deck",
                cards=[
                    RemoteDeckCard(
                        7,
                        3,
                        "mainboard",
                        None,
                        "normal",
                        name="Remote Ambiguous Card",
                    )
                ],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                preview = import_deck_url(
                    db_path,
                    source_url="https://aetherhub.com/Deck/test-ambiguous",
                    default_inventory="personal",
                    dry_run=True,
                )

            self.assertFalse(preview["ready_to_commit"])
            self.assertEqual(0, preview["rows_written"])
            self.assertEqual(3, preview["summary"]["requested_card_quantity"])
            self.assertEqual(3, preview["summary"]["unresolved_card_quantity"])
            self.assertEqual(1, len(preview["resolution_issues"]))
            issue = preview["resolution_issues"][0]
            self.assertEqual("ambiguous_card_name", issue["kind"])
            self.assertEqual(7, issue["source_position"])
            self.assertEqual("mainboard", issue["section"])
            self.assertEqual(
                {("remote-ambiguous-main", "normal"), ("remote-ambiguous-other", "normal")},
                {(option["scryfall_id"], option["finish"]) for option in issue["options"]},
            )

            with self.assertRaisesRegex(ValidationError, "Unresolved remote deck import ambiguities remain."):
                import_deck_url(
                    db_path,
                    source_url="https://aetherhub.com/Deck/test-ambiguous",
                    default_inventory="personal",
                    dry_run=False,
                    source_snapshot_token=preview["source_snapshot_token"],
                )

            committed = import_deck_url(
                db_path,
                source_url="https://aetherhub.com/Deck/test-ambiguous",
                default_inventory="personal",
                dry_run=False,
                source_snapshot_token=preview["source_snapshot_token"],
                resolutions=[
                    {
                        "source_position": 7,
                        "scryfall_id": "remote-ambiguous-other",
                        "finish": "normal",
                    }
                ],
            )
            self.assertTrue(committed["ready_to_commit"])
            self.assertEqual("remote-ambiguous-other", committed["imported_rows"][0]["scryfall_id"])
            self.assertEqual(7, committed["imported_rows"][0]["source_position"])

    def test_import_deck_url_snapshot_token_avoids_refetch_between_preview_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="snapshot-card",
                oracle_id="snapshot-oracle",
                name="Snapshot Card",
                collector_number="9",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="archidekt",
                source_url="https://archidekt.com/decks/456/test",
                deck_name="Snapshot Deck",
                cards=[RemoteDeckCard(3, 2, "mainboard", "snapshot-card", "normal")],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ) as fetch_remote_deck_source:
                preview = import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/456/test",
                    default_inventory="personal",
                    dry_run=True,
                )
                self.assertEqual(1, fetch_remote_deck_source.call_count)

                committed = import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/456/test",
                    default_inventory="personal",
                    dry_run=False,
                    source_snapshot_token=preview["source_snapshot_token"],
                )

            self.assertEqual(1, fetch_remote_deck_source.call_count)
            self.assertEqual(2, committed["imported_rows"][0]["quantity"])

    def test_import_deck_url_rejects_tampered_snapshot_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="tamper-card",
                oracle_id="tamper-oracle",
                name="Tamper Card",
                collector_number="1",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="archidekt",
                source_url="https://archidekt.com/decks/987/test",
                deck_name="Tamper Deck",
                cards=[RemoteDeckCard(1, 1, "mainboard", "tamper-card", "normal")],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                preview = import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/987/test",
                    default_inventory="personal",
                    dry_run=True,
                    snapshot_signing_secret="custom-secret",
                )

            padded_token = preview["source_snapshot_token"] + "=" * (-len(preview["source_snapshot_token"]) % 4)
            container = json.loads(base64.urlsafe_b64decode(padded_token.encode("ascii")).decode("utf-8"))
            container["payload"]["source"]["deck_name"] = "Tampered Deck"
            tampered_token = base64.urlsafe_b64encode(
                json.dumps(container, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).decode("ascii")

            with self.assertRaisesRegex(ValidationError, "source_snapshot_token is invalid."):
                import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/987/test",
                    default_inventory="personal",
                    dry_run=False,
                    source_snapshot_token=tampered_token,
                    snapshot_signing_secret="custom-secret",
                )

    def test_import_deck_url_rejects_expired_snapshot_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="expired-card",
                oracle_id="expired-oracle",
                name="Expired Card",
                collector_number="1",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="archidekt",
                source_url="https://archidekt.com/decks/654/test",
                deck_name="Expired Deck",
                cards=[RemoteDeckCard(1, 1, "mainboard", "expired-card", "normal")],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                with patch("mtg_source_stack.inventory.deck_url_import.time.time", return_value=100):
                    preview = import_deck_url(
                        db_path,
                        source_url="https://archidekt.com/decks/654/test",
                        default_inventory="personal",
                        dry_run=True,
                        snapshot_signing_secret="custom-secret",
                    )

            with patch("mtg_source_stack.inventory.deck_url_import.time.time", return_value=5000):
                with self.assertRaisesRegex(ValidationError, "source_snapshot_token has expired. Re-run preview."):
                    import_deck_url(
                        db_path,
                        source_url="https://archidekt.com/decks/654/test",
                        default_inventory="personal",
                        dry_run=False,
                        source_snapshot_token=preview["source_snapshot_token"],
                        snapshot_signing_secret="custom-secret",
                    )

    def test_import_deck_url_snapshot_token_depends_on_signing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="secret-card",
                oracle_id="secret-oracle",
                name="Secret Card",
                collector_number="1",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            remote_source = RemoteDeckSource(
                provider="archidekt",
                source_url="https://archidekt.com/decks/321/test",
                deck_name="Secret Deck",
                cards=[RemoteDeckCard(1, 1, "mainboard", "secret-card", "normal")],
            )

            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                preview = import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/321/test",
                    default_inventory="personal",
                    dry_run=True,
                    snapshot_signing_secret="custom-secret",
                )

            with self.assertRaisesRegex(ValidationError, "source_snapshot_token is invalid."):
                import_deck_url(
                    db_path,
                    source_url="https://archidekt.com/decks/321/test",
                    default_inventory="personal",
                    dry_run=False,
                    source_snapshot_token=preview["source_snapshot_token"],
                    snapshot_signing_secret="wrong-secret",
                )

    def test_import_deck_url_rejects_missing_inventory(self) -> None:
        remote_source = RemoteDeckSource(
            provider="archidekt",
            source_url="https://archidekt.com/decks/123/test",
            deck_name="Remote Deck",
            cards=[RemoteDeckCard(1, 1, "mainboard", "main-card", "normal")],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            with patch(
                "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                return_value=remote_source,
            ):
                with self.assertRaisesRegex(ValidationError, "default_inventory is required for deck URL imports."):
                    import_deck_url(
                        db_path,
                        source_url="https://archidekt.com/decks/123/test",
                        default_inventory=None,
                    )


if __name__ == "__main__":
    unittest.main()
