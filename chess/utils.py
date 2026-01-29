import random
from datetime import timedelta


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
        user=user,
        theme__is_trainable=True
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
