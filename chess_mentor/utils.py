import random
from datetime import timedelta
import sys
import importlib
import importlib.util

def get_chess_lib():
    """
    Import and return the python-chess library, avoiding conflict with the app named 'chess'.
    """
    # Find site-packages directories
    site_packages_dirs = []
    for path in sys.path:
        if isinstance(path, str) and 'site-packages' in path:
            site_packages_dirs.append(path)
    
    # Try to find chess module in site-packages using find_spec
    for site_dir in site_packages_dirs:
        try:
            # Look for chess module in this directory
            spec = importlib.util.find_spec('chess', [site_dir])
            if spec is None:
                continue
            # Create a new module with unique name to avoid conflict
            chesslib = importlib.util.module_from_spec(spec)
            # Load the module
            spec.loader.exec_module(chesslib)
            if hasattr(chesslib, 'Board'):
                return chesslib
        except Exception:
            continue
    
    # Last resort: try direct import with path manipulation and module removal
    original_path = sys.path.copy()
    filtered = [p for p in sys.path if p not in ['', '/home/deybis/Repos/entrena-chess']]
    sys.path = filtered
    
    # Temporarily remove 'chess' from sys.modules if it's our local app
    original_module = sys.modules.get('chess')
    if original_module and hasattr(original_module, '__file__') and 'site-packages' not in original_module.__file__:
        # Remove it temporarily
        del sys.modules['chess']
    
    try:
        chesslib = importlib.import_module('chess')
        if hasattr(chesslib, 'Board'):
            return chesslib
        else:
            raise ImportError("chess module doesn't have Board class")
    except ImportError as e:
        raise ImportError(f"Cannot import python-chess library: {e}")
    finally:
        # Restore original module if needed
        if original_module:
            sys.modules['chess'] = original_module
        sys.path[:] = original_path


def get_week_cycle_dates(today):
    """
    Devuelve (start_date, end_date) del ciclo semanal lunes-viernes
    """
    start = today - timedelta(days=today.weekday())  # lunes
    end = start + timedelta(days=6)                   # domingo
    return start, end


def pick_cycle_theme(cycle_themes):
    """
    Ponderación:
    P1 → 50%
    P2 → 30%
    P3 → 20%
    """
    weighted = []

    for ct in cycle_themes:
        if ct.priority == 1:
            weighted.extend([ct] * 5)
        elif ct.priority == 2:
            weighted.extend([ct] * 3)
        elif ct.priority == 3:
            weighted.extend([ct] * 2)

    return random.choice(weighted)


def get_weakest_themes(user, limit=10):
    """
    Devuelve los temas más débiles (menor Elo) de un usuario.
    """
    from .models import ThemeElo
    weakest = ThemeElo.objects.filter(
        user=user
    ).order_by("elo")[:limit]
    return [wt.theme for wt in weakest]


def select_blitz_puzzles(user):
    """
    Selecciona 30 puzzles para el modo Blitz Tactics.
    Basado en los 10 temas más débiles y rating del jugador -300 ±100.
    """
    from django.db.models import Avg
    from .repository import LichessDB
    from .models import Elo, ThemeElo
    
    # Obtener rating general del jugador
    user_elo_obj = Elo.objects.filter(user=user).first()
    if user_elo_obj:
        player_rating = user_elo_obj.elo
    else:
        # Si no tiene Elo general, usar promedio de temas
        avg_elo = ThemeElo.objects.filter(user=user).aggregate(
            avg=Avg("elo")
        )["avg"] or 1200
        player_rating = int(avg_elo)
    
    # Límites de rating de la base de datos (consistentes con importación)
    DB_RATING_MIN = 1500
    DB_RATING_MAX = 2800
    
    target_rating = player_rating - 300
    # Asegurar que target_rating esté dentro de los límites de la base de datos
    target_rating = max(DB_RATING_MIN, min(DB_RATING_MAX, target_rating))
    
    rating_min = max(DB_RATING_MIN, target_rating - 50)
    rating_max = min(DB_RATING_MAX, target_rating + 50)
    
    # Asegurar que rating_min <= rating_max
    if rating_min > rating_max:
        rating_min, rating_max = rating_max, rating_min  # intercambiar si es necesario
    if rating_min == rating_max:
        # Expandir un poco el rango si es igual
        rating_min = max(DB_RATING_MIN, rating_min - 50)
        rating_max = min(DB_RATING_MAX, rating_max + 50)
    
    # Garantizar que rating_min <= rating_max (seguridad adicional)
    if rating_min > rating_max:
        rating_min = DB_RATING_MIN
        rating_max = DB_RATING_MAX
    
    # Obtener temas más débiles
    weakest_themes = get_weakest_themes(user, limit=10)
    theme_names = [theme.lichess_name for theme in weakest_themes]
    
    db = LichessDB()
    
    # Estrategia: intentar obtener 30 puzzles de una vez
    # 1. Con rating ajustado y temas específicos
    puzzles = db.get_random_puzzles(
        rating_min=rating_min,
        rating_max=rating_max,
        themes=theme_names,
        limit=30
    )
    
    # 2. Si no hay suficientes, relajar rating (±150 en lugar de ±50)
    if len(puzzles) < 30:
        rating_min = max(DB_RATING_MIN, player_rating - 450)
        rating_max = min(DB_RATING_MAX, player_rating - 150)
        # Asegurar que rating_min <= rating_max
        if rating_min > rating_max:
            rating_min, rating_max = rating_max, rating_min
        if rating_min == rating_max:
            rating_min = max(DB_RATING_MIN, rating_min - 50)
            rating_max = min(DB_RATING_MAX, rating_max + 50)
        
        # Garantizar que rating_min <= rating_max (seguridad adicional)
        if rating_min > rating_max:
            rating_min = DB_RATING_MIN
            rating_max = DB_RATING_MAX
        
        additional = db.get_random_puzzles(
            rating_min=rating_min,
            rating_max=rating_max,
            themes=theme_names,
            limit=30 - len(puzzles)
        )
        # Filtrar duplicados
        existing_ids = {p["puzzle_id"] for p in puzzles}
        for puzzle in additional:
            if puzzle["puzzle_id"] not in existing_ids:
                puzzles.append(puzzle)
                existing_ids.add(puzzle["puzzle_id"])
    
    # 3. Si aún no hay suficientes, permitir cualquier tema (mismo rating relajado)
    if len(puzzles) < 30:
        additional = db.get_random_puzzles(
            rating_min=rating_min,
            rating_max=rating_max,
            themes=None,
            limit=30 - len(puzzles)
        )
        # Filtrar duplicados
        existing_ids = {p["puzzle_id"] for p in puzzles}
        for puzzle in additional:
            if puzzle["puzzle_id"] not in existing_ids:
                puzzles.append(puzzle)
                existing_ids.add(puzzle["puzzle_id"])
    
    # 4. Último recurso: cualquier puzzle en rango más amplio
    if len(puzzles) < 30:
        rating_min = max(DB_RATING_MIN, player_rating - 500)
        rating_max = min(DB_RATING_MAX, player_rating - 100)
        if rating_min > rating_max:
            rating_min = DB_RATING_MIN
            rating_max = DB_RATING_MAX
        additional = db.get_random_puzzles(
            rating_min=rating_min,
            rating_max=rating_max,
            themes=None,
            limit=30 - len(puzzles)
        )
        existing_ids = {p["puzzle_id"] for p in puzzles}
        for puzzle in additional:
            if puzzle["puzzle_id"] not in existing_ids:
                puzzles.append(puzzle)
                existing_ids.add(puzzle["puzzle_id"])
    
    # Solo necesitamos los IDs (asegurarnos de tener exactamente 30 o menos si no hay suficientes)
    puzzle_ids = [p["puzzle_id"] for p in puzzles[:30]]
    return puzzle_ids





def generate_random_position(min_pieces=5, max_pieces=10, exercise_number=1):
    """
    Genera una posición aleatoria de ajedrez válida con min_pieces a max_pieces.
    Siempre incluye ambos reyes. Balancea los colores para evitar sesgo.
    Los peones blancos solo en filas 2-6, peones negros en filas 3-7.
    Evita posiciones en jaque al inicio.

    Límites de piezas:
    - 1 Reina máximo total (cualquier color)
    - 2 Torres máximo por color
    - 2 Alfiles máximo por color
    - 2 Caballos máximo por color
    - 8 Peones máximo por color

    Dificultad progresiva:
    - Ejercicios 1-7: Solo piezas menores (P, B, N)
    - Ejercicios 8-15: Todas las piezas (P, B, N, R, Q)
    """
    chesslib = get_chess_lib()

    while True:
        board = chesslib.Board(fen=None)
        king_squares = random.sample(list(chesslib.SQUARES), 2)
        board.set_piece_at(king_squares[0], chesslib.Piece(chesslib.KING, chesslib.WHITE))
        board.set_piece_at(king_squares[1], chesslib.Piece(chesslib.KING, chesslib.BLACK))

        total_pieces = random.randint(min_pieces, max_pieces)
        remaining = total_pieces - 2
        if remaining <= 0:
            continue

        available_squares = [sq for sq in chesslib.SQUARES if sq not in king_squares]
        if len(available_squares) < remaining:
            continue

        chosen_squares = random.sample(available_squares, remaining)

        total_pieces = 2 + remaining

        min_white_total = (total_pieces + 2) // 3
        min_white_to_add = max(0, min_white_total - 1)

        max_white_total = (total_pieces * 2) // 3
        max_white_to_add = max_white_total - 1

        min_white = max(0, min_white_to_add)
        max_white = min(remaining, max_white_to_add)

        if max_white < min_white:
            max_white = min_white
        if min_white > max_white:
            min_white = max_white

        white_pieces_to_add = random.randint(min_white, max_white)
        black_pieces_to_add = remaining - white_pieces_to_add

        colors_list = [chesslib.WHITE] * white_pieces_to_add + [chesslib.BLACK] * black_pieces_to_add
        random.shuffle(colors_list)

        queen_placed = False
        per_color_counts = {
            chesslib.WHITE: {"B": 0, "N": 0, "R": 0, "P": 0},
            chesslib.BLACK: {"B": 0, "N": 0, "R": 0, "P": 0}
        }

        all_minor_pieces = ["P", "B", "N"]
        all_pieces = ["P", "N", "B", "R", "Q"]

        for i, sq in enumerate(chosen_squares):
            color = colors_list[i]

            if exercise_number <= 7:
                pieces_pool = all_minor_pieces.copy()
            else:
                pieces_pool = all_pieces.copy()

            available_pieces = []
            for p in pieces_pool:
                if p == "Q":
                    if not queen_placed:
                        available_pieces.append(p)
                elif p == "R":
                    if per_color_counts[color]["R"] < 2:
                        available_pieces.append(p)
                elif p == "B":
                    if per_color_counts[color]["B"] < 2:
                        available_pieces.append(p)
                elif p == "N":
                    if per_color_counts[color]["N"] < 2:
                        available_pieces.append(p)
                elif p == "P":
                    if per_color_counts[color]["P"] < 8:
                        available_pieces.append(p)

            if not available_pieces:
                break

            piece_type = random.choice(available_pieces)

            if piece_type == "P":
                row = chesslib.square_rank(sq)
                if color == chesslib.WHITE and row >= 6:
                    fallback = [p for p in ["N", "B"] if per_color_counts[color][p] < 2]
                    if fallback:
                        piece_type = random.choice(fallback)
                    else:
                        continue
                elif color == chesslib.BLACK and row <= 1:
                    fallback = [p for p in ["N", "B"] if per_color_counts[color][p] < 2]
                    if fallback:
                        piece_type = random.choice(fallback)
                    else:
                        continue

            if piece_type == "Q":
                queen_placed = True
            elif piece_type in per_color_counts[color]:
                per_color_counts[color][piece_type] += 1

            piece = chesslib.Piece.from_symbol(piece_type.lower() if color == chesslib.BLACK else piece_type)
            board.set_piece_at(sq, piece)

        valid = True
        for sq in chesslib.SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.piece_type == chesslib.PAWN:
                row = chesslib.square_rank(sq)
                if row == 0 or row == 7:
                    valid = False
                    break
        if not valid:
            continue

        board.turn = random.choice([chesslib.WHITE, chesslib.BLACK])

        if not board.is_valid():
            continue

        original_turn = board.turn
        board.turn = chesslib.WHITE
        white_check = board.is_check()
        board.turn = chesslib.BLACK
        black_check = board.is_check()
        board.turn = original_turn

        if white_check or black_check:
            continue

        return board


def select_vision_rush_exercises(user):
    """
    Selecciona 15 ejercicios para el modo Vision Rush.
    Genera posiciones aleatorias y preguntas dinámicamente.
    """
    try:
        chesslib = get_chess_lib()
        
        def count_pieces(board, color):
            count = 0
            for sq in chesslib.SQUARES:
                piece = board.piece_at(sq)
                if piece and piece.color == color:
                    count += 1
            return count
        
        def count_captures(board, color):
            captures = 0
            for move in board.legal_moves:
                if board.is_capture(move):
                    moving_piece = board.piece_at(move.from_square)
                    if moving_piece and moving_piece.color == color:
                        captures += 1
            return captures
        
        def count_checks(board, color):
            checks = 0
            for move in board.legal_moves:
                board_copy = board.copy()
                board_copy.push(move)
                if board_copy.is_check():
                    moving_piece = board.piece_at(move.from_square)
                    if moving_piece and moving_piece.color == color:
                        checks += 1
            return checks
        
        def legal_moves_for_piece(board, piece_type, square):
            piece = board.piece_at(square)
            if not piece or piece.piece_type != piece_type:
                return 0
            moves = 0
            for move in board.legal_moves:
                if move.from_square == square:
                    moves += 1
            return moves
        
        def find_piece_square(board, piece_type, color):
            for sq in chesslib.SQUARES:
                piece = board.piece_at(sq)
                if piece and piece.piece_type == piece_type and piece.color == color:
                    return chesslib.square_name(sq)
            return None
        
        def piece_symbol_to_spanish(symbol):
            """Convierte símbolo de pieza (P, N, B, R, Q, K) a nombre en español."""
            mapping = {
                'P': 'peón',
                'N': 'caballo', 
                'B': 'alfil',
                'R': 'torre',
                'Q': 'dama',
                'K': 'rey'
            }
            return mapping.get(symbol, symbol)
        
        def get_piece_article(symbol):
            """Devuelve el artículo correcto ('el' o 'la') para la pieza."""
            feminine_pieces = {'R', 'Q'}  # torre, dama
            return 'la' if symbol in feminine_pieces else 'el'
        
        def get_color_adjective(piece_symbol, side):
            """Devuelve el adjetivo de color correcto ('blanco', 'negra', etc.) para la pieza."""
            feminine_pieces = {'R', 'Q'}  # torre, dama
            if side == 'w':
                return 'blanca' if piece_symbol in feminine_pieces else 'blanco'
            else:
                return 'negra' if piece_symbol in feminine_pieces else 'negro'
        
        exercises = []
        attempts = 0
        while len(exercises) < 15 and attempts < 50:
            try:
                # Determinar rango de piezas basado en el número de ejercicios generados
                exercises_count = len(exercises)
                if exercises_count < 5:
                    min_pieces, max_pieces = 4, 6
                elif exercises_count < 10:
                    min_pieces, max_pieces = 6, 8
                else:
                    min_pieces, max_pieces = 8, 10
                
                board = generate_random_position(
                    min_pieces=min_pieces,
                    max_pieces=max_pieces,
                    exercise_number=len(exercises) + 1
                )
                
                # Determinar color que tiene el turno (quién mueve)
                turn_color = board.turn  # chesslib.WHITE o chesslib.BLACK
                turn_side = 'w' if turn_color == chesslib.WHITE else 'b'
                turn_color_name = 'blanco' if turn_side == 'w' else 'negro'
                turn_color_name_plural = 'blancas' if turn_side == 'w' else 'negras'
                
                # Elegir tipo de pregunta aleatorio
                exercise_types = [
                    'count_pieces',
                    'count_captures',
                    'count_checks',
                    'legal_moves_piece',
                    'piece_square'
                ]
                ex_type = random.choice(exercise_types)
                
                if ex_type == 'count_pieces':
                    # Usar el color que tiene el turno
                    side = turn_side
                    color = turn_color
                    count = count_pieces(board, color)
                    question = {
                        'type': 'count_pieces',
                        'side': side,
                        'text': f'¿Cuántas piezas {turn_color_name_plural} hay en el tablero?'
                    }
                    correct_answer = str(count)
                
                elif ex_type == 'count_captures':
                    # Usar el color que tiene el turno
                    side = turn_side
                    color = turn_color
                    count = count_captures(board, color)
                    question = {
                        'type': 'count_captures',
                        'side': side,
                        'text': f'¿Cuántas capturas puede realizar el {turn_color_name}?'
                    }
                    correct_answer = str(count)
                
                elif ex_type == 'count_checks':
                    # Usar el color que tiene el turno
                    side = turn_side
                    color = turn_color
                    count = count_checks(board, color)
                    question = {
                        'type': 'count_checks',
                        'side': side,
                        'text': f'¿Cuántos jaques puede dar el {turn_color_name}?'
                    }
                    correct_answer = str(count)
                
                elif ex_type == 'legal_moves_piece':
                    # Preferir piezas del color que tiene el turno
                    pieces_turn = []
                    pieces_other = []
                    for sq in chesslib.SQUARES:
                        piece = board.piece_at(sq)
                        if piece and piece.piece_type != chesslib.KING:
                            if piece.color == turn_color:
                                pieces_turn.append((sq, piece))
                            else:
                                pieces_other.append((sq, piece))
                    
                    # Usar piezas del color del turno si hay, si no, cualquier pieza
                    if pieces_turn:
                        pieces = pieces_turn
                    else:
                        pieces = pieces_other
                    
                    if not pieces:
                        # Fallback: cualquier pieza (incluyendo reyes)
                        for sq in chesslib.SQUARES:
                            piece = board.piece_at(sq)
                            if piece:
                                pieces.append((sq, piece))
                    
                    sq, piece = random.choice(pieces)
                    piece_symbol = chesslib.piece_symbol(piece.piece_type).upper()
                    square_name = chesslib.square_name(sq)
                    count = legal_moves_for_piece(board, piece.piece_type, sq)
                    piece_name = piece_symbol_to_spanish(piece_symbol)
                    article = get_piece_article(piece_symbol)
                    question = {
                        'type': 'legal_moves_piece',
                        'piece': piece_symbol,
                        'square': square_name,
                        'text': f'¿Cuántas jugadas legales puede realizar {article} {piece_name} en {square_name}?'
                    }
                    correct_answer = str(count)
                
                elif ex_type == 'piece_square':
                    # Contar piezas por tipo y color para identificar piezas únicas
                    piece_counts = {}
                    for sq in chesslib.SQUARES:
                        piece = board.piece_at(sq)
                        if piece:
                            key = (piece.piece_type, piece.color)
                            piece_counts[key] = piece_counts.get(key, 0) + 1
                    
                    # Solo piezas con exactamente una ocurrencia (sin ambigüedad)
                    unique_pieces = [(pt, c) for (pt, c), count in piece_counts.items() if count == 1]
                    
                    if not unique_pieces:
                        attempts += 1
                        continue
                    
                    # Separar por el color que tiene el turno
                    turn_unique = [(pt, c) for (pt, c) in unique_pieces if c == turn_color]
                    other_unique = [(pt, c) for (pt, c) in unique_pieces if c != turn_color]
                    
                    # 80% de probabilidad de elegir del color que tiene el turno
                    if turn_unique and random.random() < 0.8:
                        piece_type, color = random.choice(turn_unique)
                    elif turn_unique:
                        piece_type, color = random.choice(turn_unique)
                    elif other_unique:
                        piece_type, color = random.choice(other_unique)
                    else:
                        piece_type, color = random.choice(unique_pieces)
                    
                    square = find_piece_square(board, piece_type, color)
                    
                    piece_symbol = chesslib.piece_symbol(piece_type).upper()
                    side = 'w' if color == chesslib.WHITE else 'b'
                    color_name = get_color_adjective(piece_symbol, side)
                    piece_name = piece_symbol_to_spanish(piece_symbol)
                    article = get_piece_article(piece_symbol)
                    question = {
                        'type': 'piece_square',
                        'piece': piece_symbol,
                        'side': side,
                        'text': f'¿En qué casilla se encuentra {article} {piece_name} {color_name}?'
                    }
                    correct_answer = square
                
                else:
                    # Default fallback
                    side = 'w'
                    color = chesslib.WHITE
                    count = count_pieces(board, color)
                    question = {
                        'type': 'count_pieces',
                        'side': side,
                        'text': '¿Cuántas piezas blancas hay en el tablero?'
                    }
                    correct_answer = str(count)
                
                exercises.append({
                    'fen': board.fen(),
                    'question': question,
                    'correct_answer': correct_answer
                })
                
                attempts = 0  # Reset attempts on success
                
            except Exception as e:
                print(f"Error generating exercise: {e}", file=sys.stderr)
                attempts += 1
                continue
        
        if len(exercises) < 15:
            print(f"Warning: Only generated {len(exercises)} exercises for Vision Rush", file=sys.stderr)
            # Add fallback exercises to reach 15
            while len(exercises) < 15:
                exercises.append({
                    "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    "question": {
                        "type": "count_pieces",
                        "side": "w",
                        "text": "¿Cuántas piezas blancas hay en el tablero?"
                    },
                    "correct_answer": "16"
                })
        
        return exercises
        
    except Exception as e:
        print(f"Error in select_vision_rush_exercises: {e}", file=sys.stderr)
        # Fallback: ejercicios básicos
        return [
            {
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "question": {
                    "type": "count_pieces",
                    "side": "w",
                    "text": "¿Cuántas piezas blancas hay en el tablero?"
                },
                "correct_answer": "16"
            }
        ]
