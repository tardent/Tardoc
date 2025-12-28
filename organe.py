import argparse
import csv
from dataclasses import dataclass
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

import pyperclip

# ------------------ CONFIG ------------------

DEFAULT_CSV = Path("organe.csv")

HEADER_KUERZEL = "kuerzel"
HEADER_NUMMER = "item_order"
HEADER_TEXT = "text"
HEADER_ACTIVE = "active"
HEADER_BILATERAL = "bilateral"
HEADER_ORGAN = "organ"

USE_ACTIVE = False  # set True later maybe

TRUTHY = {"1", "true", "yes", "y", "ja", "j"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interaktive klinische Befund-Zusammenfassung aus CSV"
    )

    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Pfad zur CSV-Datei (default: organe.csv)",
    )

    parser.add_argument(
        "--active",
        action="store_true",
        help="Nur aktive Einträge aus der CSV verwenden",
    )

    parser.add_argument(
        "--no-clipboard",
        action="store_true",
        help="Ergebnis NICHT in die Zwischenablage kopieren",
    )

    return parser.parse_args()


# ------------------ DATA MODEL ------------------

@dataclass(frozen=True)
class Item:
    kuerzel: str
    nummer: int
    text: str
    bilateral: bool
    active: bool = True


@dataclass(frozen=True)
class Entry:
    side: Optional[str]  # "LINKS", "RECHTS", or None
    text: str


# ------------------ INPUT HELPERS ------------------


def ask_tokens(prompt: str) -> list[str]:
    return [p.strip() for p in input(prompt).split(",") if p.strip()]


def ask_numbers(prompt: str) -> set[int]:
    out: set[int] = set()
    for token in ask_tokens(prompt):
        try:
            out.add(int(token))
        except ValueError:
            print(f"Ignoriere ungültige Nummer: {token!r}")
    return out


def parse_bool(value: str, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in TRUTHY


# ------------------ CSV READING ------------------

def iter_items_from_csv(csv_path: Path,* , include_active: bool = False) -> Iterable[Item]:
    with DEFAULT_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kuerzel = row[HEADER_KUERZEL].strip().lower()
            nummer = int(row[HEADER_NUMMER].strip())
            text = row[HEADER_TEXT].strip()
            bilateral = parse_bool(row.get(HEADER_BILATERAL, ""), default=False)

            active = True
            if include_active:
                active = parse_bool(row.get(HEADER_ACTIVE, "1"), default=True)

            yield Item(
                kuerzel=kuerzel,
                nummer=nummer,
                text=text,
                bilateral=bilateral,
                active=active,
            )


def load_organs_menu(csv_path: Path) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    with DEFAULT_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            organ = (row.get(HEADER_ORGAN) or "").strip()
            kuerzel = (row.get(HEADER_KUERZEL) or "").strip().lower()
            if organ and kuerzel:
                pairs.add((organ, kuerzel))
    return sorted(pairs, key=lambda x: (x[0].lower(), x[1]))


def select_items_for_kuerzel(
    selected_kuerzel: list[str],
    *,
    csv_path: Path,
    use_active: bool,
) -> list[Item]:
    wanted = {k.strip().lower() for k in selected_kuerzel if k.strip()}
    items = [
        item
        for item in iter_items_from_csv(csv_path, include_active=use_active)
        if item.kuerzel in wanted and (not use_active or item.active)
    ]
    return sorted(items, key=lambda it: it.nummer)



# ------------------ UI PRINTING ------------------

def print_organs_menu(menu: list[tuple[str, str]]) -> None:
    print("\nVerfügbare Auswahl (Organ – Kürzel):")
    for organ, kuerzel in menu:
        print(f"- {organ} – {kuerzel}")


def show_options(items: list[Item]) -> None:
    print("\nOptionen:")
    for item in items:
        print(f"{item.nummer}: {item.text}")


# ------------------ MAIN WORKFLOW ------------------

def input_organs(csv_path: Path, *, use_active: bool) -> list[Item]:
    menu = load_organs_menu(csv_path)
    print_organs_menu(menu)

    selected = ask_tokens("\nWelche Kürzel sind gewünscht? (z.B. h, l, o) ")
    items = select_items_for_kuerzel(
        selected,
        csv_path=csv_path,
        use_active=use_active,
    )

    show_options(items)
    return items


def replace_pathological(items: list[Item]) -> tuple[list[Entry], list[Entry]]:
    chosen = ask_numbers("Wo gibt es Auffälligkeiten? (Nummern) ? ")

    normal: list[Entry] = []
    pathological: list[Entry] = []

    for item in items:
        is_chosen = item.nummer in chosen

        if is_chosen and item.bilateral:
            left = input(f"LINKS (leer = normal) – {item.text}:\n> ").strip()
            right = input(f"RECHTS (leer = normal) – {item.text}:\n> ").strip()

            (pathological if left else normal).append(Entry("LINKS", left or item.text))
            (pathological if right else normal).append(Entry("RECHTS", right or item.text))

        elif is_chosen:
            new_text = input(f"Pathologisch (leer = normal) – {item.text}:\n> ").strip()
            (pathological if new_text else normal).append(Entry(None, new_text or item.text))

        else:
            if item.bilateral:
                normal.append(Entry("LINKS", item.text))
                normal.append(Entry("RECHTS", item.text))
            else:
                normal.append(Entry(None, item.text))

    return normal, pathological


def build_summary_text(normal: list[Entry], pathological: list[Entry]) -> str:
    def bucket(entries: list[Entry]) -> dict[Optional[str], list[str]]:
        d: dict[Optional[str], list[str]] = defaultdict(list)
        for e in entries:
            d[e.side].append(e.text)
        return d

    pn = bucket(pathological)
    nn = bucket(normal)

    patho_parts: list[str] = []
    if pn.get("LINKS"):
        patho_parts.append(f"LINKS {', '.join(pn['LINKS'])}")
    if pn.get("RECHTS"):
        patho_parts.append(f"RECHTS {', '.join(pn['RECHTS'])}")
    if pn.get(None):
        patho_parts.append(", ".join(pn[None]))

    normal_parts: list[str] = []
    if nn.get("LINKS"):
        normal_parts.append(f"LINKS ({', '.join(nn['LINKS'])})")
    if nn.get("RECHTS"):
        normal_parts.append(f"RECHTS ({', '.join(nn['RECHTS'])})")
    if nn.get(None):
        normal_parts.append(", ".join(nn[None]))

    patho_line = " ".join(patho_parts) if patho_parts else "-"
    normal_line = "; ".join(normal_parts) if normal_parts else "-"

    return f"Pathologisch: {patho_line}\nNormal: {normal_line}"


def main() -> None:
    args = parse_args()

    items = input_organs(
        csv_path=args.csv,
        use_active=args.active,
    )

    normal, pathological = replace_pathological(items)
    out = build_summary_text(normal, pathological)

    print(out)

    if not args.no_clipboard:
        pyperclip.copy(out)
        print("\nIn Zwischenablage kopiert (Strg+V zum Einfügen).")



if __name__ == "__main__":
    main()
