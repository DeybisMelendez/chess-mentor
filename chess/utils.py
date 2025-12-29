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
