import random
import sqlite3
from pathlib import Path

from django.conf import settings


class LichessDB:
    """
    Acceso a la base de datos de puzzles de Lichess (SQLite).

    - Conexión persistente (optimizada para PythonAnywhere)
    - Random rápido con rnd precomputado
    - Filtro por rating + theme(s)
    - Lookup directo por puzzle_id
    """

    _conn = None  # conexión compartida
    _indexes_created = False  # índices creados

    def __init__(self):
        self.db_path = Path(settings.BASE_DIR) / "lichess_puzzles.sqlite3"

    def connect(self):
        """
        Devuelve una conexión SQLite persistente.
        Solo lectura.
        """
        if self.__class__._conn is None:
            conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False
            )
            
            # Asegurar que los índices existan (solo una vez)
            self._ensure_indexes(conn)

            self.__class__._conn = conn

        return self.__class__._conn
    
    def _ensure_indexes(self, conn):
        """
        Crear índices necesarios para mejorar rendimiento si no existen.
        """
        if self.__class__._indexes_created:
            return
        
        cursor = conn.cursor()
        
        # Lista de índices a crear
        indexes = [
            ("idx_puzzles_rating_rnd", "puzzles (rating, rnd)"),
            ("idx_puzzle_themes_theme_id", "puzzle_themes (theme_id)"),
            ("idx_themes_name", "themes (name)"),
        ]
        
        for idx_name, idx_def in indexes:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx_name,)
            )
            if not cursor.fetchone():
                try:
                    cursor.execute(f"CREATE INDEX {idx_name} ON {idx_def}")
                except Exception as e:
                    # Log error pero continuar
                    import sys
                    print(f"Warning: Could not create index {idx_name}: {e}", file=sys.stderr)
        
        conn.commit()
        self.__class__._indexes_created = True

    def get_board_orientation(self, fen):
        try:
            return "white" if fen.split()[1] == "b" else "black"
        except Exception:
            return "white"

    # =====================================================
    # Random óptimo por rating + theme(s)
    # =====================================================
    def get_random_puzzle(self, rating_min=0, rating_max=3000, themes=None):
        themes = themes or []

        conn = self.connect()
        cursor = conn.cursor()

        rnd = random.randint(0, 2**31 - 1)

        # Construir condiciones WHERE
        where = ["p.rating BETWEEN ? AND ?", "p.rnd >= ?"]
        params = [rating_min, rating_max, rnd]

        if themes:
            # Usar EXISTS en lugar de JOIN para mejor rendimiento
            where.append("""
                EXISTS (
                    SELECT 1 FROM puzzle_themes pt
                    JOIN themes t ON t.id = pt.theme_id
                    WHERE pt.puzzle_id = p.puzzle_id
                      AND t.name IN ({})
                )
            """.format(",".join("?" * len(themes))))
            params.extend(themes)

        where_sql = " AND ".join(where)

        # Query principal
        cursor.execute(f"""
            SELECT p.puzzle_id, p.fen, p.moves, p.rating
            FROM puzzles p
            WHERE {where_sql}
            ORDER BY p.rnd
            LIMIT 1
        """, params)

        row = cursor.fetchone()

        if not row:
            where_wrap = ["p.rating BETWEEN ? AND ?"]
            params_wrap = [rating_min, rating_max]

            if themes:
                where_wrap.append("""
                    EXISTS (
                        SELECT 1 FROM puzzle_themes pt
                        JOIN themes t ON t.id = pt.theme_id
                        WHERE pt.puzzle_id = p.puzzle_id
                          AND t.name IN ({})
                    )
                """.format(",".join("?" * len(themes))))
                params_wrap.extend(themes)

            where_wrap_sql = " AND ".join(where_wrap)

            cursor.execute(f"""
                SELECT p.puzzle_id, p.fen, p.moves, p.rating
                FROM puzzles p
                WHERE {where_wrap_sql}
                ORDER BY p.rnd
                LIMIT 1
            """, params_wrap)

            row = cursor.fetchone()

        if not row:
            return None

        puzzle_id, fen, moves, rating = row

        # Obtener todos los themes del puzzle
        cursor.execute("""
            SELECT t.name
            FROM themes t
            JOIN puzzle_themes pt ON pt.theme_id = t.id
            WHERE pt.puzzle_id = ?
        """, (puzzle_id,))

        theme_list = [r[0] for r in cursor.fetchall()]

        return {
            "puzzle_id": puzzle_id,
            "fen": fen,
            "moves": moves.split(),
            "rating": rating,
            "orientation": self.get_board_orientation(fen),
            "themes": theme_list,
        }

    # =====================================================
    # Random múltiple óptimo por rating + theme(s)
    # =====================================================
    def get_random_puzzles(self, rating_min=0, rating_max=3000, themes=None, limit=30):
        """
        Devuelve múltiples puzzles aleatorios que cumplan los criterios.
        Usa JOIN con DISTINCT para mejor compatibilidad y rendimiento con índices.
        """
        themes = themes or []
        
        conn = self.connect()
        cursor = conn.cursor()
        
        rnd = random.randint(0, 2**31 - 1)
        
        join = ""
        where = [
            "p.rating BETWEEN ? AND ?",
            "p.rnd >= ?",
        ]
        params = [rating_min, rating_max, rnd]
        
        if themes:
            join = """
                JOIN puzzle_themes pt ON pt.puzzle_id = p.puzzle_id
                JOIN themes t ON t.id = pt.theme_id
            """
            where.append(
                "t.name IN ({})".format(",".join("?" * len(themes)))
            )
            params.extend(themes)
        
        where_sql = " AND ".join(where)
        
        # Query principal para obtener puzzles
        cursor.execute(f"""
            SELECT DISTINCT
                p.puzzle_id,
                p.fen,
                p.moves,
                p.rating
            FROM puzzles p
            {join}
            WHERE {where_sql}
            ORDER BY p.rnd
            LIMIT ?
        """, params + [limit])
        
        rows = cursor.fetchall()
        
        # Si no encontramos suficientes, intentar sin la condición rnd >= ?
        if len(rows) < limit:
            where_wrap = ["p.rating BETWEEN ? AND ?"]
            params_wrap = [rating_min, rating_max]
            
            if themes:
                where_wrap.append(
                    "t.name IN ({})".format(",".join("?" * len(themes)))
                )
                params_wrap.extend(themes)
            
            where_wrap_sql = " AND ".join(where_wrap)
            
            cursor.execute(f"""
                SELECT DISTINCT
                    p.puzzle_id,
                    p.fen,
                    p.moves,
                    p.rating
                FROM puzzles p
                {join}
                WHERE {where_wrap_sql}
                ORDER BY p.rnd
                LIMIT ?
            """, params_wrap + [limit])
            
            rows = cursor.fetchall()
        
        if not rows:
            return []
        
        # Obtener IDs para buscar temas
        puzzle_ids = [row[0] for row in rows]
        
        # Obtener todos los themes para estos puzzles en una sola consulta
        placeholders = ",".join("?" * len(puzzle_ids))
        cursor.execute(f"""
            SELECT pt.puzzle_id, t.name
            FROM themes t
            JOIN puzzle_themes pt ON pt.theme_id = t.id
            WHERE pt.puzzle_id IN ({placeholders})
        """, puzzle_ids)
        
        theme_rows = cursor.fetchall()
        
        # Organizar themes por puzzle_id
        themes_by_puzzle = {}
        for puzzle_id, theme_name in theme_rows:
            if puzzle_id not in themes_by_puzzle:
                themes_by_puzzle[puzzle_id] = []
            themes_by_puzzle[puzzle_id].append(theme_name)
        
        # Construir resultado
        puzzles = []
        for puzzle_id, fen, moves, rating in rows:
            puzzles.append({
                "puzzle_id": puzzle_id,
                "fen": fen,
                "moves": moves.split(),
                "rating": rating,
                "orientation": self.get_board_orientation(fen),
                "themes": themes_by_puzzle.get(puzzle_id, []),
            })
        
        return puzzles

    # =====================================================
    # Lookup directo por ID
    # =====================================================
    def get_puzzle_by_id(self, puzzle_id):
        conn = self.connect()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT puzzle_id, fen, moves, rating
            FROM puzzles
            WHERE puzzle_id = ?
        """, (puzzle_id,))

        row = cursor.fetchone()
        if not row:
            return None

        puzzle_id, fen, moves, rating = row

        cursor.execute("""
            SELECT t.name
            FROM themes t
            JOIN puzzle_themes pt ON pt.theme_id = t.id
            WHERE pt.puzzle_id = ?
        """, (puzzle_id,))

        theme_list = [r[0] for r in cursor.fetchall()]

        return {
            "puzzle_id": puzzle_id,
            "fen": fen,
            "moves": moves.split(),
            "rating": rating,
            "orientation": self.get_board_orientation(fen),
            "themes": theme_list,
        }
