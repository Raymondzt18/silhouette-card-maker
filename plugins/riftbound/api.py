from os import path
from re import compile, search
from enum import Enum
from urllib.parse import quote
import cloudscraper
from time import sleep

PILTOVER_URL_TEMPLATE = 'https://cdn.piltoverarchive.com/cards/{card_number}.webp'
RIFTMANA_URL_TEMPLATE = 'https://riftmana.com/wp-content/uploads/Cards/{card_number}.webp'
RIFTMANA_SEARCH_URL_TEMPLATE = 'https://riftmana.com/wp-json/riftmana/v2/cards/search?search={query}'

BASE_CARD_ID_PATTERN = compile(r'^[A-Z0-9]+-\d+$')

class ImageServer(str, Enum):
    PILTOVER = 'piltover_archive'
    RIFTMANA = 'riftmana'

# Create a persistent cloudscraper session for connection pooling
scraper = cloudscraper.create_scraper()

def request_api(query: str) -> cloudscraper.CloudScraper:
    r = scraper.get(query, headers = {'user-agent': 'silhouette-card-maker/0.1', 'accept': '*/*'})

    # Check for 2XX response code
    r.raise_for_status()

    sleep(0.075)

    return r

def normalize_card_number(card_number: str) -> str:
    if not card_number:
        return card_number

    alternate_art_suffix_pattern = compile(r'^([A-Z0-9]+-\d+)[a-z]?$')
    match = search(alternate_art_suffix_pattern, card_number)
    if match:
        return match.group(1)

    return card_number


def normalize_card_number_for_standard_art(card_number: str) -> str:
    if not card_number:
        return card_number

    # Prefer the regular card version over any overnumbered or alternate-art suffixes.
    # Examples: "SET-235" or "SET-235a" should resolve to "SET-199" when the card
    # shares the same base name but has a standard counterpart.
    if card_number.endswith('a'):
        return card_number[:-1]

    if card_number.endswith('s'):
        return card_number[:-1]

    return card_number


def fetch_card_art(index: int, card_number: str, quantity: int, source: ImageServer, front_img_dir: str):
    card_number = normalize_card_number_for_standard_art(normalize_card_number(card_number))

    url_template = PILTOVER_URL_TEMPLATE
    if source == ImageServer.RIFTMANA:
        url_template = RIFTMANA_URL_TEMPLATE

    image_server_query = url_template.format(card_number=card_number)
    api_response = request_api(image_server_query)

    # Otherwise, try to retrieve the art for the signature art of the card since the request failed for alternate art
    if api_response is None:
        alternate_art_suffix_pattern = compile(r'^([A-Z0-9]+-\d+)a$')
        match = search(alternate_art_suffix_pattern, card_number)
        if match:
            image_server_query = url_template.format(card_number=f'{match.group(1)}s')
            api_response = request_api(image_server_query)

    if api_response is not None:
        card_art = api_response.content

        if card_art is not None:
            # Save image based on quantity
            for counter in range(quantity):
                image_path = path.join(front_img_dir, f'{index}{card_number}_{counter + 1}.jpg')

                with open(image_path, 'wb') as f:
                    f.write(card_art)

def fetch_card_number(name: str) -> str:
    # Resolve a card name to its card number via Riftmana's card search API.
    url = RIFTMANA_SEARCH_URL_TEMPLATE.format(query=quote(name))
    search_response = request_api(url)

    cards = search_response.json().get('data', {}).get('cards', [])
    if not cards:
        return None

    # The search can return multiple printings of the same name across sets
    # (reprints) and multiple variants of the same printing (alternate art,
    # promos). Prefer an exact name match over a fuzzy one, and within that,
    # prefer the base card ID (no alternate-art/promo suffix) as the default.
    normalized_name = name.strip().lower()
    exact_matches = [card for card in cards if (card.get('name') or '').strip().lower() == normalized_name]
    candidates = exact_matches or cards

    for card in candidates:
        card_id = card.get('card_id')
        if card_id and BASE_CARD_ID_PATTERN.match(card_id):
            return card_id

    return candidates[0].get('card_id')

def get_handle_card(
    source: ImageServer,
    front_img_dir: str
):
    def configured_fetch_card(index: int, card_number: str, quantity: int):
        fetch_card_art(
            index,
            card_number,
            quantity,
            source,
            front_img_dir
        )

    return configured_fetch_card
