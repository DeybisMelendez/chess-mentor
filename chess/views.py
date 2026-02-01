import json
import random
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum, Avg
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.core.paginator import Paginator
from django.utils import timezone
from django.utils.timezone import make_aware
from django.views.decorators.http import require_POST

from .models import (ActiveExercise, BlitzTacticsAttempt, BlitzTacticsSession,
                     Elo, PuzzleAttempt, RetryPuzzle, Theme,
                     ThemeElo, TrainingCycle, TrainingCycleTheme,
                     TrainingPreferences)
from .repository import LichessDB
from .utils import get_week_cycle_dates, get_weakest_themes, pick_cycle_theme, select_blitz_puzzles


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
        # Todos los temas del ciclo
        cycle_theme_names = [
            ct.theme.lichess_name
            for ct in cycle_themes
        ]

        # Rating promedio de los temas del ciclo
        theme_elos = ThemeElo.objects.filter(
            user=user,
            theme__in=[ct.theme for ct in cycle_themes]
        )
        base_elo = (
            theme_elos.aggregate(avg=Avg("elo"))["avg"]
            or 1200
        )

        # Ventana de ±100 puntos
        puzzle = db.get_random_puzzle(
            rating_min=max(0, int(base_elo - 100)),
            rating_max=int(base_elo + 100),
            themes=cycle_theme_names,
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

    if not puzzle_data:
        return JsonResponse(
            {"status": "error", "message": "Puzzle not found"},
            status=404,
        )

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
        user=user,
        theme__is_trainable=True
    ).select_related("theme").order_by("elo", "theme__name")[:5]
    
    # Temas más fuertes (mayor Elo)
    strongest_themes = ThemeElo.objects.filter(
        user=user,
        theme__is_trainable=True
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
    else:
        page_obj = None

    context = {
        "cycles": cycles,
        "selected_cycle": selected_cycle,
        "attempts": attempts,
        "solved_count": solved_count,
        "failed_count": failed_count,
        "total_count": total_count,
        "page_obj": page_obj,
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
    Crea una nueva sesión de Blitz Tactics para hoy.
    """
    user = request.user
    today = timezone.now().date()
    
    # Verificar que no exista una sesión activa
    existing = BlitzTacticsSession.objects.filter(
        user=user,
        date=today
    ).first()
    if existing:
        if existing.is_active:
            return redirect("blitz_tactics_puzzle")
        else:
            # Si ya existe pero está completada, podemos crear una nueva? 
            # Según reglas, solo una por día. Podemos redirigir a resultados.
            return redirect("blitz_tactics_results", session_id=existing.id)
    
    # Seleccionar puzzles
    puzzle_ids = select_blitz_puzzles(user)
    
    # Crear sesión
    session = BlitzTacticsSession.objects.create(
        user=user,
        date=today,
        puzzles=puzzle_ids,
        time_remaining=180,  # 3 minutos
        failures=0,
        completed=False,
        score=0,
    )
    
    # Redirigir al primer puzzle
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
    sessions = BlitzTacticsSession.objects.filter(
        user=request.user
    ).order_by("-date")
    
    context = {
        "sessions": sessions,
    }
    return render(request, "blitz_tactics_history.html", context)
