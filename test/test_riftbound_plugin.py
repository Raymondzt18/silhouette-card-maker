"""
Tests for the Riftbound plugin.
Tests deck format parsing and image fetching from Piltover Archive/Riftmana.
"""
import os
import shutil
import tempfile
from unittest.mock import patch

import pytest

from plugins.riftbound.deck_formats import DeckFormat, parse_deck, parse_tts
from plugins.riftbound.api import request_api, get_handle_card, ImageServer, fetch_card_number
from plugins.riftbound.format_deck import parse_unformatted_deck
from plugins.riftbound.generate_card_index import build_index


def _search_response(cards):
    """Build a fake requests.Response-like object matching Riftmana's
    /riftmana/v2/cards/search shape, as consumed by fetch_card_number()."""
    class FakeResponse:
        def json(self_inner):
            return {'success': True, 'data': {'cards': cards}}
    return FakeResponse()


# --- Unit Tests for Deck Format Parsing ---

class TestTTSFormat:
    """Test Tabletop Simulator format parsing."""

    def test_parse_tts(self):
        """Test parsing TTS format (space-separated card codes)."""
        deck_text = "OGN-265-1 OGN-246-1 OGN-245-1"

        parsed_cards = []
        def collect_card(index, card_number, quantity):
            parsed_cards.append({
                'index': index,
                'card_number': card_number,
                'quantity': quantity
            })

        parse_tts(deck_text, collect_card)

        assert len(parsed_cards) == 3
        assert parsed_cards[0]['card_number'] == "OGN-265"
        assert parsed_cards[1]['card_number'] == "OGN-246"


class TestPiltoverArchiveFormat:
    """Test Piltover Archive format parsing."""

    def test_piltover_archive_line_pattern(self):
        """Test that Piltover Archive line pattern matches correctly."""
        import re
        pattern = re.compile(r'^(\d+) (.+)$')

        # Valid lines
        assert pattern.match("1 Viktor, Herald of the Arcane")
        assert pattern.match("3 Seal of Unity")

        # Invalid lines
        assert not pattern.match("")
        assert not pattern.match("Viktor, Herald of the Arcane")  # No quantity

    def test_piltover_archive_uses_regular_art_code(self):
        """Test that alternate-art suffixes are stripped for Piltover Archive cards."""
        parsed_cards = []

        def collect_card(index, card_number, quantity):
            parsed_cards.append((card_number, quantity))

        with patch("plugins.riftbound.deck_formats.fetch_card_number", return_value="SET-123a"):
            parse_deck("1 Some Card", DeckFormat.PILTOVER, collect_card)

        assert parsed_cards == [("SET-123", 1)]


class TestFetchCardNumber:
    """Test fetch_card_number()'s selection logic against Riftmana's card
    search API response shape (mocked, no network)."""

    def test_prefers_base_card_id_over_variants(self):
        """When several printings/variants share a name, the base (non-suffixed)
        card ID should be preferred over alternate-art/promo variants."""
        cards = [
            {'card_id': 'OGN-126', 'name': 'Body Rune'},
            {'card_id': 'OGN-126a', 'name': 'Body Rune'},
            {'card_id': 'OGN-126b', 'name': 'Body Rune'},
        ]
        with patch('plugins.riftbound.api.request_api', return_value=_search_response(cards)):
            assert fetch_card_number('Body Rune') == 'OGN-126'

    def test_prefers_exact_name_match(self):
        """A fuzzy/unrelated result sharing a substring should lose to an exact
        (case-insensitive) name match elsewhere in the result list."""
        cards = [
            {'card_id': 'OGN-001', 'name': 'Blazing Scorcher'},
            {'card_id': 'OGN-245', 'name': 'Seal of Unity'},
        ]
        with patch('plugins.riftbound.api.request_api', return_value=_search_response(cards)):
            assert fetch_card_number('seal of unity') == 'OGN-245'

    def test_no_results_returns_none(self):
        with patch('plugins.riftbound.api.request_api', return_value=_search_response([])):
            assert fetch_card_number('Not A Real Card') is None

    def test_falls_back_to_first_result_when_no_base_id(self):
        """If every candidate has a suffix (no clean base ID), just take the first."""
        cards = [
            {'card_id': 'OGN-265-p', 'name': 'Viktor, Herald of the Arcane'},
            {'card_id': 'OGN-308s', 'name': 'Viktor, Herald of the Arcane'},
        ]
        with patch('plugins.riftbound.api.request_api', return_value=_search_response(cards)):
            assert fetch_card_number('Viktor, Herald of the Arcane') == 'OGN-265-p'


class TestBuildCardIndex:
    """Test generate_card_index.py's build_index(), which groups a flat card
    list (as returned by Riftmana's search API, paginated across all cards)
    into the name -> card number mapping shipped as riftbound-card-index.json."""

    def test_groups_by_lowercased_name_and_picks_base_id(self):
        cards = [
            {'card_id': 'OGN-126', 'name': 'Body Rune'},
            {'card_id': 'OGN-126a', 'name': 'Body Rune'},
            {'card_id': 'OGN-245', 'name': 'Seal of Unity'},
        ]
        index = build_index(cards)
        assert index == {
            'body rune': 'OGN-126',
            'seal of unity': 'OGN-245',
        }

    def test_skips_cards_with_no_name(self):
        cards = [{'card_id': 'OGN-001', 'name': ''}, {'card_id': 'OGN-002', 'name': 'Brazen Buccaneer'}]
        index = build_index(cards)
        assert index == {'brazen buccaneer': 'OGN-002'}


class TestParseUnformattedDeck:
    """Test format_deck.py's parse_unformatted_deck() against both supported
    paste shapes: plain decklist exports (section headers + "N Name" lines)
    and marketplace pastes (name line + separate "N x $price" line)."""

    def test_plain_decklist_with_section_headers(self):
        """Section headers like 'MainDeck:'/'Rune Pool:'/'Champion:' are skipped,
        and cards whose names contain a header keyword (e.g. 'Mind Rune') are
        still parsed as cards rather than mistaken for a 'Rune Pool:' heading."""
        deck_text = """Legend:
1 Jayce, Defender of Tomorrow

Champion:
1 Jayce, Man of Progress

MainDeck:
3 Elder Dragon
2 Wages of Pain
1 Sabotage

Battlefields:
1 Sigil of the Storm

Rune Pool:
7 Body Rune
5 Mind Rune

Sideboard:
2 Sabotage
1 Wages of Pain
"""
        cards = parse_unformatted_deck(deck_text)

        assert cards["Jayce, Defender of Tomorrow"] == 1
        assert cards["Jayce, Man of Progress"] == 1
        assert cards["Elder Dragon"] == 3
        assert cards["Sigil of the Storm"] == 1
        assert cards["Body Rune"] == 7
        assert cards["Mind Rune"] == 5
        # Same card name appearing in multiple sections sums across the deck.
        assert cards["Wages of Pain"] == 3
        assert cards["Sabotage"] == 3
        assert len(cards) == 8

    def test_marketplace_paste_shape_still_works(self):
        """Regression: the original 'name line, then N x $price line' shape
        (e.g. a copy-pasted missing-cards list) must keep working unchanged."""
        deck_text = """LeBlanc, Deceiver
1 × $0.16
$0.16
Champions · 1 missing
$0.26

Order Rune
6 × $0.13
$0.78

Mind Rune
2 × $0.09
$0.18
Sideboard · 3 missing
$3.10
"""
        cards = parse_unformatted_deck(deck_text)

        assert cards == {
            "LeBlanc, Deceiver": 1,
            "Order Rune": 6,
            "Mind Rune": 2,
        }


# --- Integration Tests for API and Image Fetching ---

@pytest.mark.integration
class TestRiftboundAPI:
    """Test Riftbound API requests."""

    def test_piltover_archive_api_availability(self):
        """Test that Piltover Archive API is available and responding."""
        response = request_api("https://cdn.piltoverarchive.com/cards/OGN-265.webp")
        assert response.status_code == 200


@pytest.mark.integration
class TestFullFetchWorkflow:
    """Integration tests for the complete card fetching workflow."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for test output."""
        front_dir = tempfile.mkdtemp()
        yield front_dir
        shutil.rmtree(front_dir)

    def test_fetch_single_card_tts(self, temp_dirs):
        """Test fetching a single card using TTS format."""
        front_dir = temp_dirs

        # Use a very small decklist - just 1 card
        deck_text = "OGN-265-1"

        handle_card = get_handle_card(ImageServer.PILTOVER, front_dir)
        parse_deck(deck_text, DeckFormat.TTS, handle_card)

        # Check that at least one image was created
        files = os.listdir(front_dir)
        assert len(files) >= 1

        # Verify image file has content (> 0 bytes)
        for f in files:
            file_path = os.path.join(front_dir, f)
            assert os.path.getsize(file_path) > 0

    def test_fetch_single_card_piltover(self, temp_dirs):
        """Test fetching a single card using Piltover Archive format."""
        front_dir = temp_dirs

        deck_text = "1 Seal of Unity"

        handle_card = get_handle_card(ImageServer.PILTOVER, front_dir)
        parse_deck(deck_text, DeckFormat.PILTOVER, handle_card)

        files = os.listdir(front_dir)
        assert len(files) >= 1

        for f in files:
            file_path = os.path.join(front_dir, f)
            assert os.path.getsize(file_path) > 0

    def test_fetch_with_quantity(self, temp_dirs):
        """Test fetching cards with quantity > 1."""
        front_dir = temp_dirs

        deck_text = "2 Seal of Unity"

        handle_card = get_handle_card(ImageServer.PILTOVER, front_dir)
        parse_deck(deck_text, DeckFormat.PILTOVER, handle_card)

        # Should have 2 copies of the card
        files = os.listdir(front_dir)
        assert len(files) == 2

        for f in files:
            file_path = os.path.join(front_dir, f)
            assert os.path.getsize(file_path) > 0
