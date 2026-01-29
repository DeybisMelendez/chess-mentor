import csv
import sqlite3
import random
import zlib
from pathlib import Path
from collections import defaultdict

# ----- CONFIG -----
CSV_FILE = "lichess_db_puzzle.csv"
SQLITE_FILE = "lichess_puzzles.sqlite3"

# Filtros simplificados
# Máxima desviación permitida (menor = más estable)
RATING_DEVIATION_THRESHOLD = 150
RATING_MIN = 1500                  # Rating mínimo (Elo)
RATING_MAX = 2800                  # Rating máximo (Elo)
MAX_TOTAL_PUZZLES = 700000
BATCH_SIZE = 10000                 # Lotes para importación


def create_tables(cursor):
    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS puzzles (
            puzzle_id TEXT PRIMARY KEY,
            fen BLOB NOT NULL,           -- Comprimido con zlib
            moves BLOB NOT NULL,         -- Comprimido con zlib
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


def create_indexes(cursor):
    """
    Crear índices necesarios después de la importación.
    """
    print("Creando índices...")
    indexes = [
        ("idx_puzzles_rating_rnd", "puzzles (rating, rnd)"),
        # Para consultas sin filtro de rating
        ("idx_puzzles_rnd", "puzzles (rnd)"),
        # Para filtrado por tema
        ("idx_puzzle_themes_theme_id", "puzzle_themes (theme_id)"),
        ("idx_themes_name", "themes (name)"),
        # NOTA: PRIMARY KEY (puzzle_id, theme_id) ya crea índice para puzzle_id
        # No necesitamos idx_puzzle_themes_puzzle_id ni idx_puzzle_themes_theme_puzzle
    ]

    for idx_name, idx_def in indexes:
        try:
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}")
            print(f"  Índice {idx_name} creado")
        except Exception as e:
            print(f"  Error creando índice {idx_name}: {e}")

    cursor.execute("ANALYZE")
    print("Análisis de estadísticas completado")


def convert_csv_to_sqlite():
    csv_path = Path(CSV_FILE)
    if not csv_path.exists():
        print(f"ERROR: No se encontró {CSV_FILE}")
        return

    conn = sqlite3.connect(SQLITE_FILE)
    cursor = conn.cursor()

    # Optimizar SQLite para importación masiva y mínimo tamaño
    cursor.execute("PRAGMA journal_mode=OFF")
    cursor.execute("PRAGMA synchronous=OFF")
    cursor.execute("PRAGMA cache_size=-20000")  # 20MB cache (consistente con runtime)
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA locking_mode=EXCLUSIVE")
    cursor.execute("PRAGMA page_size=4096")
    cursor.execute("PRAGMA foreign_keys=OFF")  # Desactivar FK durante importación
    cursor.execute("PRAGMA automatic_index=OFF")  # Evitar índices automáticos
    cursor.execute("PRAGMA ignore_check_constraints=ON")

    create_tables(cursor)
    conn.commit()

    theme_counter = defaultdict(int)

    total = 0
    skipped = 0
    ignored = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            # -----------------------------
            # Filtro de estabilidad (RatingDeviation)
            # -----------------------------
            try:
                if int(row["RatingDeviation"]) >= RATING_DEVIATION_THRESHOLD:
                    skipped += 1
                    continue
            except Exception:
                skipped += 1
                continue

            rating = int(row["Rating"])

            # Filtro de rating mínimo/máximo
            if rating < RATING_MIN or rating > RATING_MAX:
                ignored += 1
                continue

            # -----------------------------
            # Temas principales (ignorar aperturas para reducir temas)
            # -----------------------------
            themes = set(row["Themes"].split())
            # Ignorar OpeningTags para reducir cantidad de temas únicos
            # themes.update(row["OpeningTags"].split())

            # Filtrar temas no deseados (muy raros o irrelevantes)
            # Lista de temas principales de ajedrez
            CHESS_THEMES = {
                # Temas estratégicos
                "middlegame", "endgame", "opening",
                # Tácticos
                "mate", "mateIn1", "mateIn2", "mateIn3", "mateIn4", "mateIn5",
                "fork", "pin", "skewer", "discoveredAttack", "doubleCheck",
                "deflection", "decoy", "interference", "zugzwang",
                "sacrifice", "clearance", "xRayAttack", "windmill",
                # Patrones
                "kingsideAttack", "queensideAttack", "backRankMate",
                "smotheredMate", "arabianMate", "hookMate",
                "annihilation", "capturingDefender", "hangingPiece",
                # Finales
                "pawnEndgame", "rookEndgame", "bishopEndgame", "knightEndgame",
                "queenEndgame", "bishopPair", "oppositeColoredBishops",
                "sameColoredBishops",
                # Estratégicos
                "advantage", "crushing", "equality", "short",
                "veryLong", "master", "masterVsMaster", "superGM",
            }

            # Filtrar solo temas conocidos para reducir cantidad de temas únicos
            themes = {t for t in themes if t in CHESS_THEMES}

            # Si después de filtrar no hay temas, omitir puzzle
            if not themes:
                ignored += 1
                continue

            # Insertar puzzle (sin límites por tema/bucket)

            puzzle_id = row["PuzzleId"]
            fen = row["FEN"]
            moves = row["Moves"]
            rnd = random.randint(0, 2**31 - 1)

            # Comprimir fen y moves para ahorrar espacio
            fen_compressed = zlib.compress(fen.encode(
                'utf-8'), level=zlib.Z_BEST_COMPRESSION)
            moves_compressed = zlib.compress(moves.encode(
                'utf-8'), level=zlib.Z_BEST_COMPRESSION)

            # -----------------------------
            # Insertar puzzle
            # -----------------------------
            cursor.execute("""
                INSERT OR IGNORE INTO puzzles
                (puzzle_id, fen, moves, rating, rnd)
                VALUES (?, ?, ?, ?, ?)
            """, (puzzle_id, fen_compressed, moves_compressed, rating, rnd))

            # -----------------------------
            # Asociar temas
            # -----------------------------
            for theme in themes:
                # Total
                theme_counter[theme] += 1

                theme_id = get_or_create_theme(cursor, theme)
                cursor.execute("""
                    INSERT OR IGNORE INTO puzzle_themes (puzzle_id, theme_id)
                    VALUES (?, ?)
                """, (puzzle_id, theme_id))

            total += 1

            # Límite absoluto de seguridad
            if total >= MAX_TOTAL_PUZZLES:
                print(
                    f"Alcanzado límite máximo de {MAX_TOTAL_PUZZLES} puzzles")
                break

            if total % BATCH_SIZE == 0:
                conn.commit()
                print(f"{total} puzzles importados...")

    conn.commit()

    # Cambiar a modo operacional normal (consistente con repository.py)
    print("Optimizando base de datos para operación...")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA journal_size_limit=16384")  # Limitar WAL a 16MB
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-20000")  # 20MB cache (consistente)
    cursor.execute("PRAGMA mmap_size=134217728")  # 128MB mmap (consistente)
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA busy_timeout=3000")  # 3 segundos timeout
    cursor.execute("PRAGMA optimize")
    cursor.execute("PRAGMA foreign_keys=OFF")  # Mejorar rendimiento lectura
    cursor.execute("PRAGMA page_size=4096")
    conn.commit()

    # Crear índices
    create_indexes(cursor)
    conn.commit()

    # Compactar base de datos para reducir tamaño
    print("Compactando base de datos (VACUUM)...")
    cursor.execute("VACUUM")
    conn.commit()

    conn.close()

    print("==========================================")
    print("Importación terminada")
    print(f"Puzzles insertados: {total}")
    print(f"Puzzles descartados por rating deviation: {skipped}")
    print(
        f"Puzzles fuera de rango rating ({RATING_MIN}-{RATING_MAX}): {ignored}")

    print("\n--- Resumen por tema ---")
    for theme, count in sorted(theme_counter.items(), key=lambda x: x[1], reverse=True):
        print(f"{theme:30} -> {count}")

    print("\n--- Resumen por tema ---")
    for theme, count in sorted(theme_counter.items(), key=lambda x: x[1], reverse=True):
        print(f"{theme:30} -> {count}")

    print("==========================================")


if __name__ == "__main__":
    convert_csv_to_sqlite()
