import json
import sys
from os import path, makedirs

# Add parent directory to path to allow imports when run as a script
REPO_ROOT = path.abspath(path.join(path.dirname(__file__), '..', '..'))
sys.path.insert(0, REPO_ROOT)

from plugins.riftbound.api import request_api, select_best_card_id

SEARCH_URL_TEMPLATE = 'https://riftmana.com/wp-json/riftmana/v2/cards/search?search=&page={page}'
OUTPUT_PATH = path.join(REPO_ROOT, 'hugo', 'static', 'pdf-maker', 'riftbound-card-index.json')


def fetch_all_cards() -> list:
    cards = []
    page = 1

    while True:
        response = request_api(SEARCH_URL_TEMPLATE.format(page=page))
        data = response.json()['data']
        cards.extend(data['cards'])

        print(f'Fetched page {page}/{data["pages"]} ({len(cards)}/{data["total"]} cards)')

        if page >= data['pages']:
            break
        page += 1

    return cards


def build_index(cards: list) -> dict:
    by_name = {}
    for card in cards:
        name = (card.get('name') or '').strip()
        if not name:
            continue
        by_name.setdefault(name.lower(), []).append(card)

    return {
        name: select_best_card_id(name, variants)
        for name, variants in by_name.items()
    }


def main():
    cards = fetch_all_cards()
    index = build_index(cards)

    makedirs(path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as output_file:
        json.dump(index, output_file, indent=2, sort_keys=True, ensure_ascii=False)
        output_file.write('\n')

    print(f'Wrote {len(index)} card name(s) to {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
