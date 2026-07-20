import argparse
import os
import re
from collections import OrderedDict

SECTION_HEADING_PATTERN = re.compile(r'^(.*?\b(?:Main Deck|Sideboard|Battlefields|Runes|Champions|Legend)\b.*|.*?·.*missing)$', re.IGNORECASE)
QUANTITY_LINE_PATTERN = re.compile(r'^(\d+)\s*[×x]\s*\$[\d,.]+$')
PRICE_ONLY_PATTERN = re.compile(r'^\$[\d,.]+$')


def parse_unformatted_deck(text: str) -> OrderedDict[str, int]:
    lines = [line.strip() for line in text.splitlines()]
    cards = OrderedDict()
    index = 0

    while index < len(lines):
        line = lines[index]

        if not line or SECTION_HEADING_PATTERN.match(line) or PRICE_ONLY_PATTERN.match(line):
            index += 1
            continue

        # If the current line is a quantity line, skip it; the name should already have been captured.
        if QUANTITY_LINE_PATTERN.match(line):
            index += 1
            continue

        # Look ahead for the quantity line after a card name.
        lookahead = index + 1
        while lookahead < len(lines) and not lines[lookahead]:
            lookahead += 1

        if lookahead < len(lines):
            qty_match = QUANTITY_LINE_PATTERN.match(lines[lookahead])
            if qty_match:
                quantity = int(qty_match.group(1))
                card_name = line
                if card_name in cards:
                    cards[card_name] += quantity
                else:
                    cards[card_name] = quantity
                index = lookahead + 1
                continue

        index += 1

    return cards


def write_deck_file(cards: OrderedDict[str, int], output_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as output_file:
        for card_name, quantity in cards.items():
            output_file.write(f"{quantity} {card_name}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Convert an unformatted Riftbound card list into a formatted deck.txt for fetch.py.'
    )
    parser.add_argument('input', help='Path to the unformatted card list text file.')
    parser.add_argument(
        '-o', '--output', default='game/decklist/deck.txt',
        help='Path to the output deck.txt file. Defaults to game/decklist/deck.txt.'
    )
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as input_file:
        text = input_file.read()

    cards = parse_unformatted_deck(text)

    if not cards:
        raise SystemExit('No valid cards were found in the input file.')

    write_deck_file(cards, args.output)
    print(f'Wrote {len(cards)} card entries to {args.output}')


if __name__ == '__main__':
    main()
