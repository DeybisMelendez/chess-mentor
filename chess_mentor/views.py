import json
import random
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q, Sum, Avg
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.utils import timezone
from django.utils.timezone import make_aware
from django.views.decorators.http import require_POST

from .models import (ActiveExercise, BlitzTacticsAttempt, BlitzTacticsSession,
                     Document, DocumentCategory, DocumentTag, Elo,
                     EloSnapshot, FreeActiveExercise, FreePuzzleAttempt,
                     PuzzleAttempt, RetryPuzzle, Theme, ThemeCategory,
                     ThemeElo, TrainingCycle, TrainingCycleTheme,
                     TrainingPreferences, VisionRushSession,
                     VisionRushAttempt)
from .repository import LichessDB
from .utils import (get_week_cycle_dates, get_weakest_themes,
                    select_blitz_puzzles, select_vision_rush_exercises)


def _save_elo_snapshot(user):
    """Guarda o actualiza el snapshot diario de Elo del usuario."""
    today = date.today()
    theme_elos = ThemeElo.objects.filter(user=user).select_related("theme")
    theme_elos_dict = {
        te.theme.name: te.elo for te in theme_elos
    }
    global_elo = Elo.objects.get(user=user).elo

    EloSnapshot.objects.update_or_create(
        user=user,
        date=today,
        defaults={
            "global_elo": global_elo,
            "theme_elos": theme_elos_dict,
        }
    )


@login_required
def get_puzzle(request):
    user = request.user
    today = date.today()
    db = LichessDB()

    # --------------------------------------------------
    # Ciclo semanal
    # --------------------------------------------------
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
        # Puzzle inválido → limpiar
        active.delete()

    puzzle = None

    # --------------------------------------------------
    # 2. Retry puzzle (20 % de probabilidad)
    # --------------------------------------------------
    retry = (
        RetryPuzzle.objects
        .filter(user=user)
        .order_by("-fail_count", "last_attempt_at")
        .first()
    )

    if retry and random.random() < 0.20:
        puzzle = db.get_puzzle_by_id(retry.puzzle_id)

    # --------------------------------------------------
    # 3. Puzzle aleatorio de los temas del ciclo
    # --------------------------------------------------
    if not puzzle and cycle_themes.exists():
        # Elegir un tema del ciclo con probabilidad uniforme
        cycle_themes_list = list(cycle_themes)
        chosen = random.choice(cycle_themes_list)

        # Elo especifico de ese tema
        theme_elo = ThemeElo.objects.filter(
            user=user, theme=chosen.theme
        ).first()
        base_elo = theme_elo.elo if theme_elo else 1200

        # Ventana de +-100 puntos para ese tema
        puzzle = db.get_random_puzzle(
            rating_min=max(0, int(base_elo - 100)),
            rating_max=int(base_elo + 100),
            themes=[chosen.theme.lichess_name],
        )

    # --------------------------------------------------
    # 4. Fallback absoluto: cualquier puzzle aleatorio
    # --------------------------------------------------
    if not puzzle:
        player_elo = (
            Elo.objects.filter(user=user)
            .values_list("elo", flat=True)
            .first()
            or ThemeElo.objects
            .filter(user=user)
            .aggregate(avg=Avg("elo"))["avg"]
            or 1200
        )

        # Ventana de ±200 puntos, sin filtro de tema
        puzzle = db.get_random_puzzle(
            rating_min=max(0, int(player_elo - 200)),
            rating_max=int(player_elo + 200),
            themes=None,
        )

    # --------------------------------------------------
    # 5. Seguridad final
    # --------------------------------------------------
    if not puzzle:
        raise Http404("No puzzle available")

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

    if not puzzle_data:
        return JsonResponse(
            {"status": "error", "message": "Puzzle not found"},
            status=404,
        )

    puzzle_rating = puzzle_data["rating"]
    puzzle_themes = puzzle_data["themes"]

    if solved:
        RetryPuzzle.objects.filter(
            user=user,
            puzzle_id=puzzle_id,
        ).delete()
    else:
        retry, created = RetryPuzzle.objects.get_or_create(
            user=user,
            puzzle_id=puzzle_id,
            defaults={"fail_count": 1},
        )

        update_fields = {}
        if not created:
            update_fields["fail_count"] = F("fail_count") + 1

        if puzzle_themes:
            theme_obj = Theme.objects.filter(
                lichess_name__in=puzzle_themes
            ).first()
            if theme_obj:
                update_fields["theme"] = theme_obj

        if update_fields:
            RetryPuzzle.objects.filter(pk=retry.pk).update(**update_fields)

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

    _save_elo_snapshot(user)

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
        .order_by("theme__name")
    )

    # Elos por categoría principal (promedio de temas de cada categoría)
    from django.db.models import Avg
    category_elos = (
        ThemeElo.objects
        .filter(
            user=user,
            theme__category__isnull=False
        )
        .values('theme__category__lichess_name', 'theme__category__name')
        .annotate(avg_elo=Avg('elo'))
        .order_by('theme__category__name')
    )
    
    elo_map = {}
    category_labels = []
    category_elos_list = []
    for item in category_elos:
        lichess_name = item['theme__category__lichess_name']
        category_name = item['theme__category__name']
        avg_elo = round(item['avg_elo'])
        
        # Para el gráfico de todas las categorías
        category_labels.append(category_name)
        category_elos_list.append(avg_elo)
        
        # Para la cuadrícula de las cuatro categorías principales
        if lichess_name in ['opening', 'middlegame', 'endgame', 'mate']:
            class SimpleElo:
                def __init__(self, elo):
                    self.elo = elo
            elo_map[lichess_name] = SimpleElo(avg_elo)

    category_data = {
        "labels": category_labels,
        "data": category_elos_list,
    }

    # =====================================================
    # Estadísticas generales de puzzles
    # =====================================================
    puzzle_stats = PuzzleAttempt.objects.filter(user=user).aggregate(
        total=Count('id'),
        solved_count=Count('id', filter=Q(solved=True)),
        failed_count=Count('id', filter=Q(solved=False)),
    )
    
    total_puzzles = puzzle_stats['total'] or 0
    solved_puzzles = puzzle_stats['solved_count'] or 0
    failed_puzzles = puzzle_stats['failed_count'] or 0
    
    success_rate = 0
    if total_puzzles > 0:
        success_rate = round((solved_puzzles / total_puzzles) * 100, 1)

    # =====================================================
    # Progreso semanal (últimos 7 días)
    # =====================================================
    week_ago = today - timedelta(days=7)
    weekly_stats = PuzzleAttempt.objects.filter(
        user=user,
        created_at__date__gte=week_ago,
        created_at__date__lte=today
    ).aggregate(
        weekly_total=Count('id'),
        weekly_solved_count=Count('id', filter=Q(solved=True)),
    )
    
    weekly_total = weekly_stats['weekly_total'] or 0
    weekly_solved = weekly_stats['weekly_solved_count'] or 0
    
    weekly_success_rate = 0
    if weekly_total > 0:
        weekly_success_rate = round((weekly_solved / weekly_total) * 100, 1)

    # =====================================================
    # Temas más débiles y más fuertes
    # =====================================================
    # Temas más débiles (menor Elo)
    weakest_themes = ThemeElo.objects.filter(
        user=user
    ).select_related("theme").order_by("elo", "theme__name")[:5]
    
    # Temas más fuertes (mayor Elo)
    strongest_themes = ThemeElo.objects.filter(
        user=user
    ).select_related("theme").order_by("-elo", "theme__name")[:5]

    # =====================================================
    # Progreso diario en el ciclo actual
    # =====================================================
    # Contar puzzles por día en el ciclo actual
    daily_progress = []
    if cycle:
        cycle_start = cycle.start_date
        cycle_end = cycle.end_date
        
        # Para simplificar, contamos puzzles por día en el ciclo
        daily_counts = PuzzleAttempt.objects.filter(
            user=user,
            created_at__date__gte=cycle_start,
            created_at__date__lte=cycle_end
        ).values('created_at__date').annotate(
            daily_total=Count('id'),
            daily_solved=Count('id', filter=Q(solved=True))
        ).order_by('created_at__date')
        
        for day in daily_counts:
            daily_progress.append({
                'date': day['created_at__date'],
                'total': day['daily_total'],
                'solved': day['daily_solved'],
                'failed': day['daily_total'] - day['daily_solved']
            })

    # =====================================================
    # Progreso de Blitz Tactics en el ciclo actual
    # =====================================================
    blitz_target = 5
    blitz_completed = BlitzTacticsSession.objects.filter(
        user=user,
        date__gte=cycle.start_date,
        date__lte=cycle.end_date,
        completed=True
    ).count()
    blitz_progress_percent = round((blitz_completed / blitz_target) * 100, 1) if blitz_target > 0 else 0
    if blitz_progress_percent > 100:
        blitz_progress_percent = 100

    # =====================================================
    # Progreso de Vision Rush en el ciclo actual
    # =====================================================
    vision_target = 5
    vision_completed = VisionRushSession.objects.filter(
        user=user,
        date__gte=cycle.start_date,
        date__lte=cycle.end_date,
        completed=True
    ).count()
    vision_progress_percent = round((vision_completed / vision_target) * 100, 1) if vision_target > 0 else 0
    if vision_progress_percent > 100:
        vision_progress_percent = 100

    # =====================================================
    # Cálculo de días restantes en el ciclo
    # =====================================================
    days_remaining = (cycle.end_date - today).days
    if days_remaining < 0:
        days_remaining = 0

    # =====================================================
    # Progreso del ciclo (porcentaje)
    # =====================================================
    cycle_progress_percent = 0
    if cycle.total_puzzles > 0:
        cycle_progress_percent = round((cycle.completed_puzzles / cycle.total_puzzles) * 100, 1)

    context = {
        "cycle": cycle,
        "elo": user_elo,
        "opening": elo_map.get("opening"),
        "middlegame": elo_map.get("middlegame"),
        "endgame": elo_map.get("endgame"),
        "mate": elo_map.get("mate"),
        "cycle_themes": cycle_themes,
        
        # Categorías para gráfico radar
        "category_data": category_data,
        
        # Estadísticas generales
        "total_puzzles": total_puzzles,
        "solved_puzzles": solved_puzzles,
        "failed_puzzles": failed_puzzles,
        "success_rate": success_rate,
        
        # Estadísticas semanales
        "weekly_total": weekly_total,
        "weekly_solved": weekly_solved,
        "weekly_success_rate": weekly_success_rate,
        
        # Temas
        "weakest_themes": weakest_themes,
        "strongest_themes": strongest_themes,
        
        # Progreso del ciclo
        "days_remaining": days_remaining,
        "cycle_progress_percent": cycle_progress_percent,
        "blitz_target": blitz_target,
        "blitz_completed": blitz_completed,
        "blitz_progress_percent": blitz_progress_percent,
        "vision_target": vision_target,
        "vision_completed": vision_completed,
        "vision_progress_percent": vision_progress_percent,
        "daily_progress": daily_progress,
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

    # Estadísticas por ciclo para la vista de resumen
    cycles_with_stats = []
    for cycle in cycles:
        # Puzzles
        start_dt = make_aware(
            datetime.combine(cycle.start_date, datetime.min.time())
        )
        end_dt = make_aware(
            datetime.combine(cycle.end_date, datetime.max.time())
        )
        puzzle_attempts = PuzzleAttempt.objects.filter(
            user=user,
            created_at__range=(start_dt, end_dt)
        )
        total_puzzles = puzzle_attempts.count()
        solved_puzzles = puzzle_attempts.filter(solved=True).count()
        failed_puzzles = total_puzzles - solved_puzzles
        
        # Blitz Tactics
        blitz_sessions = BlitzTacticsSession.objects.filter(
            user=user,
            date__range=(cycle.start_date, cycle.end_date)
        )
        total_blitz_sessions = blitz_sessions.count()
        total_blitz_solved = sum(session.score for session in blitz_sessions)
        total_blitz_attempted = sum(session.total_puzzles for session in blitz_sessions)
        
        # Vision Rush
        vision_sessions = VisionRushSession.objects.filter(
            user=user,
            date__range=(cycle.start_date, cycle.end_date)
        )
        total_vision_sessions = vision_sessions.count()
        total_vision_solved = sum(session.score for session in vision_sessions)
        total_vision_attempted = sum(session.total_exercises for session in vision_sessions)
        
        cycles_with_stats.append({
            "cycle": cycle,
            "puzzles": {
                "total": total_puzzles,
                "solved": solved_puzzles,
                "failed": failed_puzzles,
                "percentage": total_puzzles and (solved_puzzles / total_puzzles * 100),
            },
            "blitz_tactics": {
                "sessions": total_blitz_sessions,
                "solved": total_blitz_solved,
                "attempted": total_blitz_attempted,
                "percentage": total_blitz_attempted and (total_blitz_solved / total_blitz_attempted * 100),
            },
            "vision_rush": {
                "sessions": total_vision_sessions,
                "solved": total_vision_solved,
                "attempted": total_vision_attempted,
                "percentage": total_vision_attempted and (total_vision_solved / total_vision_attempted * 100),
            },
        })

    selected_cycle_id = request.GET.get("cycle")
    selected_cycle = None
    attempts = []
    solved_count = 0
    failed_count = 0
    total_count = 0

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
        total_count = attempts.count()
        solved_count = attempts.filter(solved=True).count()
        failed_count = total_count - solved_count

        # Paginación
        paginator = Paginator(attempts, 50)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        attempts = page_obj.object_list
        
        # Estadísticas de Blitz Tactics y Vision Rush para el ciclo seleccionado
        blitz_sessions = BlitzTacticsSession.objects.filter(
            user=user,
            date__range=(selected_cycle.start_date, selected_cycle.end_date)
        )
        total_blitz_sessions = blitz_sessions.count()
        total_blitz_solved = sum(session.score for session in blitz_sessions)
        total_blitz_attempted = sum(session.total_puzzles for session in blitz_sessions)
        
        vision_sessions = VisionRushSession.objects.filter(
            user=user,
            date__range=(selected_cycle.start_date, selected_cycle.end_date)
        )
        total_vision_sessions = vision_sessions.count()
        total_vision_solved = sum(session.score for session in vision_sessions)
        total_vision_attempted = sum(session.total_exercises for session in vision_sessions)
        
        blitz_stats = {
            "sessions": total_blitz_sessions,
            "solved": total_blitz_solved,
            "attempted": total_blitz_attempted,
            "percentage": total_blitz_attempted and (total_blitz_solved / total_blitz_attempted * 100),
        }
        vision_stats = {
            "sessions": total_vision_sessions,
            "solved": total_vision_solved,
            "attempted": total_vision_attempted,
            "percentage": total_vision_attempted and (total_vision_solved / total_vision_attempted * 100),
        }
    else:
        blitz_stats = None
        vision_stats = None
        page_obj = None

    context = {
        "cycles": cycles,
        "cycles_with_stats": cycles_with_stats,
        "selected_cycle": selected_cycle,
        "attempts": attempts,
        "solved_count": solved_count,
        "failed_count": failed_count,
        "total_count": total_count,
        "page_obj": page_obj,
        "blitz_stats": blitz_stats,
        "vision_stats": vision_stats,
    }

    return render(request, "puzzle_history.html", context)


@login_required
def theme_overview(request):
    user = request.user

    user_theme_elos = ThemeElo.objects.filter(user=user)

    # =========================
    # TODAS LAS CATEGORÍAS CON SUS TEMAS
    # =========================
    trainable_categories = (
        ThemeCategory.objects
        .prefetch_related(
            Prefetch(
                "themes",
                queryset=(
                    Theme.objects
                    .prefetch_related(
                        Prefetch(
                            "themeelo_set",
                            queryset=user_theme_elos,
                            to_attr="theme_elo"
                        )
                    )
                ),
                to_attr="trainable_themes"
            )
        )
        .order_by("name")
    )

    # Filtrar: solo categorías que tengan temas
    trainable_categories = [
        c for c in trainable_categories
        if c.trainable_themes
    ]

    # Calcular promedio de Elo por categoría
    for category in trainable_categories:
        elos = []
        for theme in category.trainable_themes:
            if hasattr(theme, 'theme_elo') and theme.theme_elo:
                # theme_elo es una lista de ThemeElo (debería tener un elemento)
                theme_elo_obj = theme.theme_elo[0] if theme.theme_elo else None
                if theme_elo_obj:
                    elos.append(theme_elo_obj.elo)
        if elos:
            category.avg_elo = sum(elos) // len(elos)
        else:
            category.avg_elo = None

    return render(
        request,
        "theme_overview.html",
        {
            "trainable_categories": trainable_categories,
            "non_trainable_categories": [],
        }
    )


@login_required
def blitz_tactics_start(request):
    """
    Página de inicio del modo Blitz Tactics.
    Si hay una sesión activa hoy, redirige al puzzle actual.
    Si no, muestra la página de inicio con botón para comenzar.
    """
    user = request.user
    today = timezone.now().date()
    
    # Buscar sesión activa de hoy
    session = BlitzTacticsSession.objects.filter(
        user=user,
        date=today
    ).first()
    
    if session and session.is_active:
        # Redirigir al puzzle actual
        return redirect("blitz_tactics_puzzle")
    
    # Si hay sesión pero no activa (completada), mostrar resultados
    completed_session = session if session and not session.is_active else None
    
    context = {
        "has_active_session": session and session.is_active,
        "completed_session": completed_session,
    }
    return render(request, "blitz_tactics_start.html", context)


@login_required
def blitz_tactics_new(request):
    """
    Crea una nueva sesión de Blitz Tactics.
    """
    user = request.user
    today = timezone.now().date()

    existing = BlitzTacticsSession.objects.filter(
        user=user,
        date=today,
        completed=False
    ).first()
    if existing and existing.is_active:
        return redirect("blitz_tactics_puzzle")

    puzzle_ids = select_blitz_puzzles(user)

    session = BlitzTacticsSession.objects.create(
        user=user,
        date=today,
        puzzles=puzzle_ids,
        time_remaining=180,
        failures=0,
        completed=False,
        score=0,
    )

    return redirect("blitz_tactics_puzzle")


@login_required
def blitz_tactics_puzzle(request):
    """
    Muestra el puzzle actual de la sesión activa.
    """
    user = request.user
    today = timezone.now().date()
    
    session = BlitzTacticsSession.objects.filter(
        user=user,
        date=today,
        completed=False
    ).first()
    
    if not session:
        # No hay sesión hoy, redirigir a inicio
        return redirect("blitz_tactics_start")
    if not session.is_active:
        # Sesión existente pero no activa (completada), mostrar resultados
        return redirect("blitz_tactics_results", session_id=session.id)
    
    current_index = session.current_puzzle_index
    if current_index >= len(session.puzzles):
        # Todos los puzzles completados
        session.completed = True
        session.save()
        return redirect("blitz_tactics_results", session_id=session.id)
    
    puzzle_id = session.puzzles[current_index]
    db = LichessDB()
    puzzle = db.get_puzzle_by_id(puzzle_id)
    
    if not puzzle:
        # Puzzle no encontrado, saltar? Marcar como fallo?
        session.record_failure()
        return redirect("blitz_tactics_puzzle")
    
    weakest_themes = get_weakest_themes(user, limit=10)
    
    context = {
        "session": session,
        "puzzle": puzzle,
        "current_puzzle": current_index + 1,
        "total_puzzles": len(session.puzzles),
        "time_remaining": session.time_remaining,
        "failures": session.failures,
        "weakest_themes": weakest_themes,
    }
    return render(request, "blitz_tactics_puzzle.html", context)


@login_required
@require_POST
@transaction.atomic
def blitz_tactics_submit(request):
    """
    Procesa el resultado del puzzle actual.
    """
    user = request.user
    data = json.loads(request.body)
    
    puzzle_id = data.get("puzzle_id")
    solved = bool(data.get("solved"))
    time_taken = data.get("time_taken")  # segundos usados
    
    today = timezone.now().date()
    session = BlitzTacticsSession.objects.filter(
        user=user,
        date=today,
        completed=False
    ).select_for_update().first()
    
    if not session:
        return JsonResponse(
            {"status": "error", "message": "No active session"},
            status=400
        )
    
    # Verificar que el puzzle_id coincida con el actual
    current_index = session.current_puzzle_index
    if current_index >= len(session.puzzles):
        return JsonResponse(
            {"status": "error", "message": "Session already completed"},
            status=400
        )
    
    if session.puzzles[current_index] != puzzle_id:
        return JsonResponse(
            {"status": "error", "message": "Puzzle mismatch"},
            status=400
        )
    
    # Restar tiempo usado (si se proporciona) - tiempo pasa siempre
    if time_taken is not None:
        try:
            time_taken_int = int(time_taken)
            if time_taken_int > 0:
                session.time_remaining = max(0, session.time_remaining - time_taken_int)
                session.save(update_fields=["time_remaining"])
        except (ValueError, TypeError):
            pass  # Ignorar si time_taken no es un número válido
    
    # Registrar intento
    BlitzTacticsAttempt.objects.create(
        session=session,
        puzzle_id=puzzle_id,
        solved=solved,
        time_taken=time_taken
    )
    
    # Actualizar Elo general y por temas (igual que en entrenamiento principal)
    db = LichessDB()
    puzzle_data = db.get_puzzle_by_id(puzzle_id)

    elo_changes = []

    if puzzle_data:
        puzzle_rating = puzzle_data["rating"]
        puzzle_themes = puzzle_data["themes"]
        score = 1.0 if solved else 0.0

        # Actualizar Elo general
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

        # Actualizar Elo por tema
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

    _save_elo_snapshot(user)

    # Registrar en PuzzleAttempt para historial general
    PuzzleAttempt.objects.create(
        user=user,
        puzzle_id=puzzle_id,
        solved=solved,
    )
    
    # Actualizar RetryPuzzle (para que aparezca en entrenamiento principal)
    if solved:
        RetryPuzzle.objects.filter(
            user=user,
            puzzle_id=puzzle_id,
        ).delete()
    else:
        retry, created = RetryPuzzle.objects.get_or_create(
            user=user,
            puzzle_id=puzzle_id,
            defaults={"fail_count": 1},
        )

        update_fields = {}
        if not created:
            update_fields["fail_count"] = F("fail_count") + 1

        if puzzle_themes:
            theme_obj = Theme.objects.filter(
                lichess_name__in=puzzle_themes
            ).first()
            if theme_obj:
                update_fields["theme"] = theme_obj

        if update_fields:
            RetryPuzzle.objects.filter(pk=retry.pk).update(**update_fields)
    
    # Actualizar sesión
    if solved:
        # Añadir 2 segundos por jugada correcta (record_success lo hace)
        session.record_success()
    else:
        session.record_failure()
    
    # Verificar si la sesión sigue activa
    if not session.is_active:
        session.completed = True
        session.save()
    
    return JsonResponse({
        "status": "ok",
        "solved": solved,
        "elo_changes": elo_changes,
        "session_status": {
            "completed": session.completed,
            "is_active": session.is_active,
            "score": session.score,
            "failures": session.failures,
            "time_remaining": session.time_remaining,
            "current_puzzle_index": session.current_puzzle_index,
        }
    })


@login_required
def blitz_tactics_results(request, session_id):
    """
    Muestra los resultados de una sesión completada.
    """
    session = get_object_or_404(
        BlitzTacticsSession,
        id=session_id,
        user=request.user
    )
    
    attempts = session.attempts.order_by("created_at")
    
    context = {
        "session": session,
        "attempts": attempts,
    }
    return render(request, "blitz_tactics_results.html", context)


@login_required
def blitz_tactics_history(request):
    """
    Historial de sesiones de Blitz Tactics del usuario.
    """
    user = request.user
    cycles = TrainingCycle.objects.filter(user=user).order_by("-start_date")
    
    selected_cycle_id = request.GET.get("cycle")
    selected_cycle = None
    sessions = BlitzTacticsSession.objects.filter(user=user).order_by("-date")
    
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
        sessions = sessions.filter(date__range=(selected_cycle.start_date, selected_cycle.end_date))
    
    total_sessions = sessions.count()
    total_puzzles_solved = sum(session.score for session in sessions)
    total_puzzles_attempted = sum(session.total_puzzles for session in sessions)
    avg_score = total_sessions and total_puzzles_solved / total_sessions
    
    context = {
        "cycles": cycles,
        "selected_cycle": selected_cycle,
        "sessions": sessions,
        "total_sessions": total_sessions,
        "total_puzzles_solved": total_puzzles_solved,
        "total_puzzles_attempted": total_puzzles_attempted,
        "avg_score": avg_score,
    }
    return render(request, "blitz_tactics_history.html", context)


@login_required
def vision_rush_start(request):
    """
    Página de inicio del modo Vision Rush.
    Si hay una sesión activa hoy, redirige al ejercicio actual.
    Si no, muestra la página de inicio con botón para comenzar.
    """
    user = request.user
    today = timezone.now().date()
    
    # Buscar sesión activa de hoy
    session = VisionRushSession.objects.filter(
        user=user,
        date=today
    ).first()
    
    if session and session.is_active:
        # Redirigir al ejercicio actual
        return redirect("vision_rush_puzzle")
    
    # Si hay sesión pero no activa (completada), mostrar resultados
    completed_session = session if session and not session.is_active else None
    
    context = {
        "has_active_session": session and session.is_active,
        "completed_session": completed_session,
    }
    return render(request, "vision_rush_start.html", context)


@login_required
def vision_rush_new(request):
    """
    Crea una nueva sesión de Vision Rush.
    """
    user = request.user
    today = timezone.now().date()

    existing = VisionRushSession.objects.filter(
        user=user,
        date=today,
        completed=False
    ).first()
    if existing and existing.is_active:
        return redirect("vision_rush_puzzle")

    exercises = select_vision_rush_exercises(user)

    session = VisionRushSession.objects.create(
        user=user,
        date=today,
        exercises=exercises,
        failures=0,
        completed=False,
        score=0,
    )

    return redirect("vision_rush_puzzle")


@login_required
def vision_rush_puzzle(request):
    """
    Muestra el ejercicio actual de la sesión activa.
    """
    user = request.user
    today = timezone.now().date()
    
    session = VisionRushSession.objects.filter(
        user=user,
        date=today,
        completed=False
    ).first()
    
    if not session:
        # No hay sesión hoy, redirigir a inicio
        return redirect("vision_rush_start")
    if not session.is_active:
        # Sesión existente pero no activa (completada), mostrar resultados
        return redirect("vision_rush_results", session_id=session.id)
    
    current_index = session.current_exercise_index
    if current_index >= len(session.exercises):
        # Todos los ejercicios completados
        session.completed = True
        session.save()
        return redirect("vision_rush_results", session_id=session.id)
    
    exercise = session.exercises[current_index]
    
    # Extraer turno del FEN (segundo campo: "w" o "b")
    fen_parts = exercise["fen"].split()
    turn = fen_parts[1] if len(fen_parts) > 1 else "w"
    
    context = {
        "session": session,
        "exercise": exercise,
        "current_exercise": current_index + 1,
        "total_exercises": len(session.exercises),
        "failures": session.failures,
        "turn": turn,
    }
    return render(request, "vision_rush_puzzle.html", context)


@login_required
@require_POST
@transaction.atomic
def vision_rush_submit(request):
    """
    Procesa el resultado del ejercicio actual.
    """
    user = request.user
    data = json.loads(request.body)
    
    user_answer = data.get("user_answer")
    solved = bool(data.get("solved"))
    memorization_time = data.get("memorization_time")
    response_time = data.get("response_time")
    
    # Convertir tiempos a float si existen
    if memorization_time is not None:
        try:
            memorization_time = float(memorization_time)
        except (ValueError, TypeError):
            memorization_time = None
    if response_time is not None:
        try:
            response_time = float(response_time)
        except (ValueError, TypeError):
            response_time = None
    
    today = timezone.now().date()
    session = VisionRushSession.objects.filter(
        user=user,
        date=today,
        completed=False
    ).select_for_update().first()
    
    if not session:
        return JsonResponse(
            {"status": "error", "message": "No active session"},
            status=400
        )
    
    # Verificar que el índice coincida
    current_index = session.current_exercise_index
    if current_index >= len(session.exercises):
        return JsonResponse(
            {"status": "error", "message": "Session already completed"},
            status=400
        )
    
    exercise = session.exercises[current_index]
    
    # Registrar intento
    attempt_data = {
        'session': session,
        'exercise_data': exercise,
        'user_answer': user_answer,
        'solved': solved,
    }
    if memorization_time is not None:
        attempt_data['memorization_time'] = memorization_time
    if response_time is not None:
        attempt_data['response_time'] = response_time
    
    VisionRushAttempt.objects.create(**attempt_data)
    
    # Actualizar sesión
    if solved:
        session.record_success()
    else:
        session.record_failure()
    
    # Verificar si la sesión sigue activa
    if not session.is_active:
        session.completed = True
        session.save()
    
    return JsonResponse({
        "status": "ok",
        "session_status": {
            "completed": session.completed,
            "is_active": session.is_active,
            "score": session.score,
            "failures": session.failures,
            "current_exercise_index": session.current_exercise_index,
        }
    })


@login_required
def vision_rush_results(request, session_id):
    """
    Muestra los resultados de una sesión completada.
    """
    session = get_object_or_404(
        VisionRushSession,
        id=session_id,
        user=request.user
    )
    
    attempts = session.attempts.order_by("created_at")
    
    # Calcular promedios de tiempos (ignorando nulls)
    from django.db.models import Avg
    avg_memorization = attempts.exclude(memorization_time__isnull=True).aggregate(
        avg=Avg('memorization_time')
    )['avg']
    avg_response = attempts.exclude(response_time__isnull=True).aggregate(
        avg=Avg('response_time')
    )['avg']
    
    context = {
        "session": session,
        "attempts": attempts,
        "avg_memorization": avg_memorization,
        "avg_response": avg_response,
    }
    return render(request, "vision_rush_results.html", context)


@login_required
def vision_rush_history(request):
    """
    Historial de sesiones de Vision Rush del usuario.
    """
    user = request.user
    cycles = TrainingCycle.objects.filter(user=user).order_by("-start_date")
    
    selected_cycle_id = request.GET.get("cycle")
    selected_cycle = None
    sessions = VisionRushSession.objects.filter(user=user).order_by("-date")
    
    if selected_cycle_id:
        selected_cycle = get_object_or_404(
            TrainingCycle,
            id=selected_cycle_id,
            user=user
        )
        sessions = sessions.filter(date__range=(selected_cycle.start_date, selected_cycle.end_date))
    
    total_sessions = sessions.count()
    total_exercises_solved = sum(session.score for session in sessions)
    total_exercises_attempted = sum(session.total_exercises for session in sessions)
    avg_score = total_sessions and total_exercises_solved / total_sessions
    
    context = {
        "cycles": cycles,
        "selected_cycle": selected_cycle,
        "sessions": sessions,
        "total_sessions": total_sessions,
        "total_exercises_solved": total_exercises_solved,
        "total_exercises_attempted": total_exercises_attempted,
        "avg_score": avg_score,
    }
    return render(request, "vision_rush_history.html", context)


def superuser_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not request.user.is_superuser:
            raise Http404
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
def documents_list(request):
    categories = DocumentCategory.objects.all().order_by("name")
    tags = DocumentTag.objects.all().order_by("name")
    documents = Document.objects.filter(is_active=True).select_related(
        "category", "uploaded_by"
    ).prefetch_related("tags")

    category_id = request.GET.get("category")
    tag_id = request.GET.get("tag")

    if category_id:
        documents = documents.filter(category_id=category_id)
    if tag_id:
        documents = documents.filter(tags__id=tag_id)

    context = {
        "documents": documents,
        "categories": categories,
        "tags": tags,
        "selected_category": category_id,
        "selected_tag": tag_id,
    }
    return render(request, "documents.html", context)


@superuser_required
def document_upload(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        category_id = request.POST.get("category")
        tag_ids = request.POST.getlist("tags")
        file = request.FILES.get("file")

        if not title or not category_id or not file:
            return render(request, "document_upload.html", {
                "categories": DocumentCategory.objects.all().order_by("name"),
                "tags": DocumentTag.objects.all().order_by("name"),
                "error": "Todos los campos son requeridos.",
            })

        category = get_object_or_404(DocumentCategory, id=category_id)

        document = Document.objects.create(
            title=title,
            description=description,
            category=category,
            file=file,
            uploaded_by=request.user,
        )

        if tag_ids:
            tags = DocumentTag.objects.filter(id__in=tag_ids)
            document.tags.set(tags)

        return redirect("documents")

    categories = DocumentCategory.objects.all().order_by("name")
    tags = DocumentTag.objects.all().order_by("name")
    return render(request, "document_upload.html", {
        "categories": categories,
        "tags": tags,
    })


@superuser_required
@require_POST
def document_delete(request, document_id):
    document = get_object_or_404(Document, id=document_id)
    document.delete()
    return redirect("documents")


@superuser_required
def categories_list(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        if name:
            DocumentCategory.objects.create(name=name, description=description)
        return redirect("categories")

    categories = DocumentCategory.objects.all().order_by("name")
    return render(request, "categories.html", {"categories": categories})


@superuser_required
def tags_list(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if name:
            DocumentTag.objects.create(name=name)
        return redirect("tags")

    tags = DocumentTag.objects.all().order_by("name")
    return render(request, "tags.html", {"tags": tags})


@superuser_required
def document_edit(request, document_id):
    document = get_object_or_404(Document, id=document_id)

    if request.method == "POST":
        document.title = request.POST.get("title", "").strip()
        document.description = request.POST.get("description", "").strip()
        category_id = request.POST.get("category")
        tag_ids = request.POST.getlist("tags")

        if category_id:
            document.category = get_object_or_404(DocumentCategory, id=category_id)

        document.save()

        if tag_ids:
            document.tags.set(DocumentTag.objects.filter(id__in=tag_ids))
        else:
            document.tags.clear()

        return redirect("documents")

    categories = DocumentCategory.objects.all().order_by("name")
    tags = DocumentTag.objects.all().order_by("name")
    return render(request, "document_edit.html", {
        "document": document,
        "categories": categories,
        "tags": tags,
    })


# =====================================================
# Entrenamiento libre (no afecta Elo)
# =====================================================

# Dificultades con rangos absolutos de rating.
FREE_RANGES = {
    "principiante":  (399, 800),
    "novato":       (800, 1200),
    "intermedio":   (1200, 1600),
    "avanzado":     (1600, 2000),
    "experto":      (2000, 2400),
    "maestro":      (2400, 2800),
    "gran-maestro": (2800, 3100),
}


def _new_free_puzzle(theme_lichess_name, rating_min, rating_max):
    """
    Obtiene un puzzle libre desde la base de datos de Lichess.

    Si no se encuentra con el tema elegido, se reintenta sin filtro de tema
    dentro del mismo rango de rating.
    """
    db = LichessDB()

    themes = [theme_lichess_name] if theme_lichess_name else []
    puzzle = db.get_random_puzzle(
        rating_min=rating_min,
        rating_max=rating_max,
        themes=themes,
    )

    if not puzzle:
        # Fallback: sin filtro de tema.
        puzzle = db.get_random_puzzle(
            rating_min=rating_min,
            rating_max=rating_max,
            themes=None,
        )

    return puzzle


@login_required
def free_training_start(request):
    """
    Página de inicio del modo de entrenamiento libre.

    Permite elegir un tema y una dificultad. Si ya existe un puzzle libre
    activo, se ofrece la opción de continuar.
    """
    user = request.user

    active = FreeActiveExercise.objects.filter(user=user).first()

    # Precarga opcional vía query params (?theme=<id>&difficulty=principiante)
    initial_theme = request.GET.get("theme", "")
    initial_difficulty = request.GET.get("difficulty", "principiante")
    if initial_difficulty not in FREE_RANGES:
        initial_difficulty = "principiante"

    # Temas agrupados por categoría para el <select>
    categories = (
        ThemeCategory.objects
        .prefetch_related("themes")
        .order_by("name")
    )

    return render(
        request,
        "free_training_start.html",
        {
            "active": active,
            "categories": categories,
            "difficulties": FREE_RANGES,
            "initial_theme": initial_theme,
            "initial_difficulty": initial_difficulty,
        },
    )


@login_required
def free_training_new(request):
    """
    Crea un nuevo puzzle libre activo con el tema y dificultad elegidos.
    """
    if request.method != "POST":
        return redirect("free_training_start")

    user = request.user

    theme_id = request.POST.get("theme_id")
    difficulty = request.POST.get("difficulty", "easy")

    if difficulty not in FREE_RANGES:
        return redirect("free_training_start")

    rating_min, rating_max = FREE_RANGES[difficulty]

    theme = None
    theme_lichess_name = ""
    if theme_id:
        theme = get_object_or_404(Theme, id=theme_id)
        theme_lichess_name = theme.lichess_name

    puzzle = _new_free_puzzle(theme_lichess_name, rating_min, rating_max)

    if not puzzle:
        return redirect("free_training_start")

    # Reemplazar cualquier puzzle libre previo.
    FreeActiveExercise.objects.filter(user=user).delete()
    FreeActiveExercise.objects.create(
        user=user,
        puzzle_id=puzzle["puzzle_id"],
        theme_lichess_name=theme_lichess_name,
        rating_min=rating_min,
        rating_max=rating_max,
    )

    return redirect("free_training_puzzle")


@login_required
def free_training_puzzle(request):
    """
    Muestra el puzzle libre activo.
    """
    user = request.user

    active = FreeActiveExercise.objects.filter(user=user).first()
    if not active:
        return redirect("free_training_start")

    db = LichessDB()
    puzzle = db.get_puzzle_by_id(active.puzzle_id)

    if not puzzle:
        # Puzzle inválido: limpiar y volver al inicio.
        active.delete()
        return redirect("free_training_start")

    theme = Theme.objects.filter(lichess_name=active.theme_lichess_name).first()

    return render(
        request,
        "free_training_puzzle.html",
        {
            "puzzle": puzzle,
            "theme": theme,
            "theme_lichess_name": active.theme_lichess_name,
            "rating_min": active.rating_min,
            "rating_max": active.rating_max,
        },
    )


@login_required
def free_training_puzzle_detail(request, puzzle_id):
    """
    Muestra un puzzle libre especifico por ID, permitiendo compartir la URL.

    Crea un FreeActiveExercise temporal para que el flujo de submit/skip
    funcione sin cambios.
    """
    user = request.user

    db = LichessDB()
    puzzle = db.get_puzzle_by_id(puzzle_id)

    if not puzzle:
        return redirect("free_training_start")

    theme_lichess_name = ""
    theme = None
    if puzzle.get("themes"):
        for t in puzzle["themes"]:
            theme = Theme.objects.filter(lichess_name=t).first()
            if theme:
                theme_lichess_name = t
                break

    rating = puzzle.get("rating", 1200)
    rating_min = max(400, rating - 400)
    rating_max = min(3100, rating + 400)

    FreeActiveExercise.objects.filter(user=user).delete()
    FreeActiveExercise.objects.create(
        user=user,
        puzzle_id=puzzle_id,
        theme_lichess_name=theme_lichess_name,
        rating_min=rating_min,
        rating_max=rating_max,
    )

    return render(
        request,
        "free_training_puzzle.html",
        {
            "puzzle": puzzle,
            "theme": theme,
            "theme_lichess_name": theme_lichess_name,
            "rating_min": rating_min,
            "rating_max": rating_max,
            "is_shared": True,
        },
    )


@login_required
@require_POST
@transaction.atomic
def free_training_submit(request):
    """
    Procesa el resultado del puzzle libre.

    Registra el intento en FreePuzzleAttempt para el historial.
    Si ``retry`` es true, mantiene el mismo puzzle activo para repetirlo.
    En caso contrario, obtiene un nuevo puzzle (mismo tema y dificultad).

    Importante: NO actualiza Elo, ThemeElo, ni el TrainingCycle.
    """
    user = request.user
    data = json.loads(request.body)

    puzzle_id = data.get("puzzle_id")
    solved = bool(data.get("solved"))
    retry = bool(data.get("retry", False))

    active = (
        FreeActiveExercise.objects
        .select_for_update()
        .filter(user=user)
        .first()
    )

    if not active or active.puzzle_id != puzzle_id:
        return JsonResponse(
            {"status": "error", "message": "Puzzle libre activo inválido"},
            status=400,
        )

    theme_lichess_name = active.theme_lichess_name
    rating_min = active.rating_min
    rating_max = active.rating_max

    FreePuzzleAttempt.objects.create(
        user=user,
        puzzle_id=puzzle_id,
        solved=solved,
        theme_lichess_name=theme_lichess_name,
        rating_min=rating_min,
        rating_max=rating_max,
    )

    active.delete()

    if retry:
        FreeActiveExercise.objects.create(
            user=user,
            puzzle_id=puzzle_id,
            theme_lichess_name=theme_lichess_name,
            rating_min=rating_min,
            rating_max=rating_max,
        )

        return JsonResponse({
            "status": "ok",
            "solved": solved,
            "retry": True,
        })

    next_puzzle = _new_free_puzzle(theme_lichess_name, rating_min, rating_max)

    if not next_puzzle:
        return JsonResponse({
            "status": "ok",
            "solved": solved,
            "next_puzzle": None,
        })

    FreeActiveExercise.objects.create(
        user=user,
        puzzle_id=next_puzzle["puzzle_id"],
        theme_lichess_name=theme_lichess_name,
        rating_min=rating_min,
        rating_max=rating_max,
    )

    return JsonResponse({
        "status": "ok",
        "solved": solved,
        "next_puzzle": next_puzzle["puzzle_id"],
        "next_puzzle_url": "/free/puzzle/",
    })


@login_required
@require_POST
@transaction.atomic
def free_training_skip(request):
    """
    Descarta el puzzle libre actual y obtiene uno nuevo con el mismo
    tema y dificultad. No cuenta como fallo.
    """
    user = request.user

    active = (
        FreeActiveExercise.objects
        .select_for_update()
        .filter(user=user)
        .first()
    )

    if not active:
        return JsonResponse(
            {"status": "error", "message": "No active puzzle"},
            status=400,
        )

    theme_lichess_name = active.theme_lichess_name
    rating_min = active.rating_min
    rating_max = active.rating_max

    active.delete()

    next_puzzle = _new_free_puzzle(theme_lichess_name, rating_min, rating_max)

    if not next_puzzle:
        return JsonResponse({
            "status": "ok",
            "next_puzzle": None,
            "redirect": "/free/",
        })

    FreeActiveExercise.objects.create(
        user=user,
        puzzle_id=next_puzzle["puzzle_id"],
        theme_lichess_name=theme_lichess_name,
        rating_min=rating_min,
        rating_max=rating_max,
    )

    return JsonResponse({
        "status": "ok",
        "next_puzzle": next_puzzle["puzzle_id"],
    })


@login_required
def free_training_history(request):
    """
    Historial de puzzles realizados en el modo de entrenamiento libre.
    """
    user = request.user

    attempts = (
        FreePuzzleAttempt.objects
        .filter(user=user)
        .order_by("-created_at")
    )

    total_count = attempts.count()
    solved_count = attempts.filter(solved=True).count()
    failed_count = total_count - solved_count

    paginator = Paginator(attempts, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "free_training_history.html",
        {
            "attempts": page_obj.object_list,
            "page_obj": page_obj,
            "total_count": total_count,
            "solved_count": solved_count,
            "failed_count": failed_count,
        },
    )


@login_required
def free_training_retry(request, puzzle_id):
    """
    Crea un FreeActiveExercise con el puzzle indicado para repetirlo
    desde el historial o desde el puzzle actual.

    Puede recibir query params opcionales ``theme`` y ``rating_min``/``rating_max``
    para preservar el contexto de dificultad.
    """
    user = request.user

    db = LichessDB()
    puzzle = db.get_puzzle_by_id(puzzle_id)

    if not puzzle:
        return redirect("free_training_history")

    theme_lichess_name = request.GET.get("theme", "")
    rating_min = request.GET.get("rating_min", 400)
    rating_max = request.GET.get("rating_max", 3100)

    try:
        rating_min = int(rating_min)
        rating_max = int(rating_max)
    except (ValueError, TypeError):
        rating_min = 400
        rating_max = 3100

    FreeActiveExercise.objects.filter(user=user).delete()
    FreeActiveExercise.objects.create(
        user=user,
        puzzle_id=puzzle_id,
        theme_lichess_name=theme_lichess_name,
        rating_min=rating_min,
        rating_max=rating_max,
    )

    return redirect("free_training_puzzle")


def analysis(request):
    return render(request, "analysis.html")


@login_required
def elo_progress(request):
    user = request.user
    today = date.today()

    days_param = request.GET.get("days", "30")
    try:
        days = int(days_param)
    except (ValueError, TypeError):
        days = 30

    cutoff = today - timedelta(days=days)

    snapshots = (
        EloSnapshot.objects
        .filter(user=user, date__gte=cutoff)
        .order_by("date")
    )

    ranges = [
        (7, "7 días"),
        (30, "30 días"),
        (90, "90 días"),
        (365, "1 año"),
    ]

    if not snapshots.exists():
        return render(request, "elo_progress.html", {
            "has_data": False,
            "selected_days": days,
            "ranges": ranges,
        })

    dates = [s.date.isoformat() for s in snapshots]
    global_elos = [s.global_elo for s in snapshots]

    all_themes = set()
    for s in snapshots:
        all_themes.update(s.theme_elos.keys())

    theme_series = {}
    for theme_name in sorted(all_themes):
        series = []
        for s in snapshots:
            series.append(s.theme_elos.get(theme_name))
        theme_series[theme_name] = series

    themes_with_category = Theme.objects.filter(
        name__in=all_themes
    ).select_related("category").values("name", "category__name")

    theme_categories = {
        t["name"]: t["category__name"] or "Sin categoría"
        for t in themes_with_category
    }

    weakest_theme_elos = (
        ThemeElo.objects
        .filter(user=user, theme__name__in=all_themes)
        .select_related("theme")
        .order_by("elo")[:10]
    )
    weakest_themes = [te.theme.name for te in weakest_theme_elos]

    start_date, end_date = get_week_cycle_dates(today)
    cycle = TrainingCycle.objects.filter(
        user=user,
        start_date=start_date,
        end_date=end_date,
    ).first()
    cycle_theme_names = []
    if cycle:
        cycle_theme_names = list(
            TrainingCycleTheme.objects
            .filter(cycle=cycle)
            .select_related("theme")
            .values_list("theme__name", flat=True)
        )

    return render(request, "elo_progress.html", {
        "has_data": True,
        "selected_days": days,
        "ranges": ranges,
        "dates": dates,
        "global_elos": global_elos,
        "theme_series": theme_series,
        "theme_categories": theme_categories,
        "weakest_themes": weakest_themes,
        "cycle_themes": cycle_theme_names,
    })
