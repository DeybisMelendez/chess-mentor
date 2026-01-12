import csv
import sqlite3
import random
from pathlib import Path
from collections import defaultdict

# ----- CONFIG -----
CSV_FILE = "lichess_db_puzzle.csv"
SQLITE_FILE = "lichess_puzzles.sqlite3"

rating_deviation_threshold = 110
BATCH_SIZE = 5000

RATING_BUCKETS = [
    (800, 1199, 1200),
    (1200, 1599, 1200),
    (1600, 1999, 600),
    (2000, 2199, 600),
    (2200, 2399, 400),
    (2400, 2500, 300),
]


def get_rating_bucket(rating):
    for low, high, _ in RATING_BUCKETS:
        if low <= rating <= high:
            return f"{low}-{high}"
    return None


def create_tables(cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS puzzles (
            puzzle_id TEXT PRIMARY KEY,
            fen TEXT NOT NULL,
            moves TEXT NOT NULL,
            rating INTEGER NOT NULL,
            rnd INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS puzzle_themes (
            puzzle_id TEXT NOT NULL,
            theme_id INTEGER NOT NULL,
            PRIMARY KEY (puzzle_id, theme_id),
            FOREIGN KEY (puzzle_id) REFERENCES puzzles(puzzle_id),
            FOREIGN KEY (theme_id) REFERENCES themes(id)
        );
    """)


def get_or_create_theme(cursor, name):
    cursor.execute("SELECT id FROM themes WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("INSERT INTO themes (name) VALUES (?)", (name,))
    return cursor.lastrowid


def convert_csv_to_sqlite():
    csv_path = Path(CSV_FILE)
    if not csv_path.exists():
        print(f"ERROR: No se encontró {CSV_FILE}")
        return

    conn = sqlite3.connect(SQLITE_FILE)
    cursor = conn.cursor()
    create_tables(cursor)
    conn.commit()

    theme_counter = defaultdict(int)
    theme_rating_counter = defaultdict(int)

    total = 0
    skipped = 0
    ignored = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # -----------------------------
            # Filtro de estabilidad
            # -----------------------------
            try:
                if int(row["RatingDeviation"]) >= rating_deviation_threshold:
                    skipped += 1
                    continue
            except Exception:
                skipped += 1
                continue

            rating = int(row["Rating"])
            bucket = get_rating_bucket(rating)

            # Fuera de los rangos definidos
            if bucket is None:
                continue

            # -----------------------------
            # Temas + aperturas
            # -----------------------------
            themes = set(row["Themes"].split())
            themes.update(row["OpeningTags"].split())

            # Ver si el puzzle aporta valor
            aporta = False
            for theme in themes:
                if theme_rating_counter[(theme, bucket)] < dict(
                    (f"{l}-{h}", m) for l, h, m in RATING_BUCKETS
                )[bucket]:
                    aporta = True
                    break

            if not aporta:
                ignored += 1
                continue

            puzzle_id = row["PuzzleId"]
            fen = row["FEN"]
            moves = row["Moves"]
            rnd = random.randint(0, 2**31 - 1)

            # -----------------------------
            # Insertar puzzle
            # -----------------------------
            cursor.execute("""
                INSERT OR IGNORE INTO puzzles
                (puzzle_id, fen, moves, rating, rnd)
                VALUES (?, ?, ?, ?, ?)
            """, (puzzle_id, fen, moves, rating, rnd))

            # -----------------------------
            # Asociar temas
            # -----------------------------
            for theme in themes:
                # Total
                theme_counter[theme] += 1

                # Por rango
                max_bucket = dict(
                    (f"{l}-{h}", m) for l, h, m in RATING_BUCKETS
                )[bucket]
                if theme_rating_counter[(theme, bucket)] < max_bucket:
                    theme_rating_counter[(theme, bucket)] += 1

                theme_id = get_or_create_theme(cursor, theme)
                cursor.execute("""
                    INSERT OR IGNORE INTO puzzle_themes (puzzle_id, theme_id)
                    VALUES (?, ?)
                """, (puzzle_id, theme_id))

            total += 1

            if total % BATCH_SIZE == 0:
                conn.commit()
                print(f"{total} puzzles importados...")

    conn.commit()
    conn.close()

    print("==========================================")
    print("Importación terminada")
    print(f"Puzzles insertados: {total}")
    print(f"Puzzles descartados por rating deviation: {skipped}")
    print(f"Puzzles ignorados (mínimos cubiertos): {ignored}")

    print("\n--- Resumen por tema ---")
    for theme, count in sorted(theme_counter.items(), key=lambda x: x[1], reverse=True):
        print(f"{theme:30} -> {count}")

    print("\n--- Resumen por tema y rango ---")
    for (theme, bucket), count in sorted(
        theme_rating_counter.items(),
        key=lambda x: (x[0][0], x[0][1])
    ):
        print(f"{theme:30} [{bucket}] -> {count}")

    print("==========================================")


if __name__ == "__main__":
    convert_csv_to_sqlite()
