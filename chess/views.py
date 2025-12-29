from datetime import date
import json
import random
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils.timezone import make_aware
from datetime import datetime
from django.db.models import Count, Q
from django.db.models import Prefetch
from django.db import transaction
from .models import (
    TrainingPreferences,
    TrainingCycle,
    TrainingCycleTheme,
    ThemeElo,
    PuzzleAttempt,
    ActiveExercise,
    RetryPuzzle,
    Elo,
    Theme,
)
from .utils import get_week_cycle_dates, pick_cycle_theme
from .repository import LichessDB


@login_required
def get_puzzle(request):
    user = request.user
    today = date.today()
    db = LichessDB()

    start_date, end_date = get_week_cycle_dates(today)

    cycle, _ = TrainingCycle.objects.get_or_create(
        user=user,
        start_date=start_date,
        end_date=end_date,
    )

    cycle_themes = cycle.themes.select_related("theme")

    # --------------------------------------------------
    # 1. Puzzle activo
    # --------------------------------------------------
    active = ActiveExercise.objects.filter(user=user).first()
    if active:
        puzzle = db.get_puzzle_by_id(active.puzzle_id)
        if puzzle:
            return render(
                request,
                "puzzle.html",
                {
                    "puzzle": puzzle,
                    "cycle": cycle,
                    "themes": cycle_themes,
                }
            )
        # Puzzle inválido → limpiar y continuar
        active.delete()

    puzzle = None

    # --------------------------------------------------
    # 2. Retry puzzle (best effort)
    # --------------------------------------------------
    retry = (
        RetryPuzzle.objects
        .filter(user=user)
        .order_by("-fail_count", "last_attempt_at")
        .first()
    )

    if retry and random.random() < 0.1:
        puzzle = db.get_puzzle_by_id(retry.puzzle_id)

    # --------------------------------------------------
    # 3. Puzzle por tema + elo
    # --------------------------------------------------
    if not puzzle:
        cycle_theme = pick_cycle_theme(cycle_themes)
        theme = cycle_theme.theme

        theme_elo = ThemeElo.objects.get(user=user, theme=theme)

        for delta in (25, 50, 75, 100, 150, 200, 250, 300):
            puzzle = db.get_random_puzzle(
                rating_min=max(0, theme_elo.elo - delta),
                rating_max=theme_elo.elo + delta,
                themes=[theme.lichess_name],
            )
            if puzzle:
                break

    ActiveExercise.objects.create(
        user=user,
        puzzle_id=puzzle["puzzle_id"],
    )

    return render(
        request,
        "puzzle.html",
        {
            "puzzle": puzzle,
            "cycle": cycle,
            "themes": cycle_themes,
        }
    )


@login_required
@require_POST
@transaction.atomic
def submit_puzzle(request):
    user = request.user
    data = json.loads(request.body)

    puzzle_id = data.get("puzzle_id")
    solved = bool(data.get("solved"))

    active = (
        ActiveExercise.objects
        .select_for_update()
        .filter(user=user)
        .first()
    )

    if not active or active.puzzle_id != puzzle_id:
        return JsonResponse(
            {"status": "error", "message": "Puzzle activo inválido"},
            status=400,
        )

    active.delete()

    PuzzleAttempt.objects.create(
        user=user,
        puzzle_id=puzzle_id,
        solved=solved,
    )

    if solved:
        RetryPuzzle.objects.filter(
            user=user,
            puzzle_id=puzzle_id,
        ).delete()
    else:
        RetryPuzzle.objects.update_or_create(
            user=user,
            puzzle_id=puzzle_id,
            defaults={"fail_count": 1},
        )

    if solved:
        today = date.today()
        cycle = (
            TrainingCycle.objects
            .filter(
                user=user,
                start_date__lte=today,
                end_date__gte=today,
            )
            .select_for_update()
            .first()
        )

        if cycle:
            cycle.completed_puzzles += 1
            cycle.save(update_fields=["completed_puzzles"])

    db = LichessDB()
    puzzle_data = db.get_puzzle_by_id(puzzle_id)

    puzzle_rating = puzzle_data["rating"]
    puzzle_themes = puzzle_data["themes"]
    score = 1.0 if solved else 0.0

    elo_changes = []

    user_elo = Elo.objects.select_for_update().get(user=user)
    old_general = user_elo.elo

    user_elo.update_elo(
        opponent_elo=puzzle_rating,
        score=score,
    )

    elo_changes.append({
        "name": "General",
        "old": old_general,
        "new": user_elo.elo,
    })

    themes = Theme.objects.filter(
        lichess_name__in=puzzle_themes
    )

    theme_elos = {
        te.theme_id: te
        for te in ThemeElo.objects.filter(
            user=user,
            theme__in=themes
        ).select_for_update()
    }

    for theme in themes:
        theme_elo = theme_elos.get(theme.id)
        if not theme_elo:
            continue  # por seguridad extrema

        old_elo = theme_elo.elo

        theme_elo.update_elo(
            opponent_elo=puzzle_rating,
            score=score,
        )

        elo_changes.append({
            "name": theme.name,
            "old": old_elo,
            "new": theme_elo.elo,
        })

    return JsonResponse(
        {
            "status": "ok",
            "solved": solved,
            "elo_changes": elo_changes,
        }
    )


@login_required
def home(request):
    user = request.user
    today = date.today()

    start_date, end_date = get_week_cycle_dates(today)

    # El ciclo se autocrea y configura vía signals
    cycle, _ = TrainingCycle.objects.get_or_create(
        user=user,
        start_date=start_date,
        end_date=end_date,
    )

    # Elo general
    user_elo = Elo.objects.get(user=user)

    # Temas del ciclo (una sola query optimizada)
    cycle_themes = (
        TrainingCycleTheme.objects
        .filter(cycle=cycle)
        .select_related("theme")
        .order_by("priority")
    )

    # Elos por categoría principal (una sola query)
    category_elos = (
        ThemeElo.objects
        .filter(
            user=user,
            theme__lichess_name__in=[
                "opening",
                "middlegame",
                "endgame",
                "mate",
            ]
        )
        .select_related("theme")
    )

    elo_map = {
        te.theme.lichess_name: te
        for te in category_elos
    }

    context = {
        "cycle": cycle,
        "elo": user_elo,
        "opening": elo_map.get("opening"),
        "middlegame": elo_map.get("middlegame"),
        "endgame": elo_map.get("endgame"),
        "mate": elo_map.get("mate"),
        "cycle_themes": cycle_themes,
    }

    return render(request, "home.html", context)


@login_required
def puzzle_history(request):
    user = request.user

    cycles = (
        TrainingCycle.objects
        .filter(user=user)
        .order_by("-start_date")
    )

    selected_cycle_id = request.GET.get("cycle")
    selected_cycle = None
    attempts = []

    if selected_cycle_id:
        selected_cycle = get_object_or_404(
            TrainingCycle,
            id=selected_cycle_id,
            user=user
        )

        start_dt = make_aware(
            datetime.combine(selected_cycle.start_date, datetime.min.time())
        )
        end_dt = make_aware(
            datetime.combine(selected_cycle.end_date, datetime.max.time())
        )

        attempts = (
            PuzzleAttempt.objects
            .filter(
                user=user,
                created_at__range=(start_dt, end_dt)
            )
            .order_by("-created_at")
        )

    context = {
        "cycles": cycles,
        "selected_cycle": selected_cycle,
        "attempts": attempts,
    }

    return render(request, "puzzle_history.html", context)


@login_required
def theme_overview(request):
    user = request.user

    user_theme_elos = ThemeElo.objects.filter(user=user)

    # =========================
    # CATEGORÍAS ENTRENABLES
    # =========================
    trainable_categories = (
        Theme.objects
        .filter(parent__isnull=True)
        .prefetch_related(
            # Elo de la categoría (si existe)
            Prefetch(
                "themeelo_set",
                queryset=user_theme_elos,
                to_attr="category_elo"
            ),
            # SOLO subtemas entrenables
            Prefetch(
                "subthemes",
                queryset=(
                    Theme.objects
                    .filter(is_trainable=True)
                    .prefetch_related(
                        Prefetch(
                            "themeelo_set",
                            queryset=user_theme_elos,
                            to_attr="theme_elo"
                        )
                    )
                ),
                to_attr="trainable_subthemes"
            )
        )
        .order_by("name")
    )

    # Filtrar: solo categorías que realmente tengan temas entrenables
    trainable_categories = [
        c for c in trainable_categories
        if c.trainable_subthemes
    ]

    # =========================
    # CATEGORÍAS NO ENTRENABLES
    # =========================
    non_trainable_categories = (
        Theme.objects
        .filter(parent__isnull=True)
        .prefetch_related(
            Prefetch(
                "themeelo_set",
                queryset=user_theme_elos,
                to_attr="category_elo"
            ),
            # TODOS los subtemas NO entrenables
            Prefetch(
                "subthemes",
                queryset=(
                    Theme.objects
                    .filter(is_trainable=False)
                    .prefetch_related(
                        Prefetch(
                            "themeelo_set",
                            queryset=user_theme_elos,
                            to_attr="theme_elo"
                        )
                    )
                ),
                to_attr="trainable_subthemes"
            )
        )
        .order_by("name")
    )

    # Filtrar:
    # - que tenga temas
    # - que NO tenga ningún tema entrenable
    non_trainable_categories = [
        c for c in non_trainable_categories
        if c.trainable_subthemes and c.subthemes.filter(is_trainable=False).exists()
    ]

    return render(
        request,
        "theme_overview.html",
        {
            "trainable_categories": trainable_categories,
            "non_trainable_categories": non_trainable_categories,
        }
    )
