import math

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TrainingPreferences(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="training_preferences"
    )
    puzzles_per_cycle = models.PositiveIntegerField(default=105)

    def __str__(self):
        return f"Preferences - {self.user}"


class Theme(models.Model):
    name = models.CharField(max_length=100, unique=True)
    lichess_name = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Nombre del tema en Lichess (solo para temas entrenables)"
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subthemes",
        help_text="Categoría padre (otro Theme)"
    )

    is_trainable = models.BooleanField(
        default=True,
        help_text="Indica si el tema puede ser entrenado directamente"
    )

    description = models.TextField(
        blank=True,
        help_text="Descripción del tema o categoría"
    )

    def clean(self):
        if self.parent is None and self.is_trainable:
            raise ValidationError(
                "Un tema entrenable debe tener una categoría padre."
            )

        if self.parent and not self.parent.is_trainable:
            pass  # OK, parent es categoría

        if self.parent and self.parent.parent:
            raise ValidationError(
                "Solo se permite un nivel de jerarquía (categoría → tema)."
            )
        
        if self.is_trainable and not self.lichess_name:
            raise ValidationError(
                "Un tema entrenable debe tener un lichess_name."
            )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} → {self.name}"
        return self.name


class TrainingCycle(models.Model):
    """
    Ciclo de entrenamiento semanal estilo Botvinnik
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="training_cycles"
    )
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField()

    total_puzzles = models.PositiveIntegerField(default=100)
    completed_puzzles = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'start_date'],
                name='unique_user_weekly_cycle'
            )
        ]

    def __str__(self):
        return f"Cycle {self.start_date} - {self.user}"


class TrainingCycleTheme(models.Model):
    cycle = models.ForeignKey(
        TrainingCycle,
        on_delete=models.CASCADE,
        related_name="themes"
    )
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE)

    priority = models.PositiveSmallIntegerField(
        default=1,
        help_text="1 = máxima prioridad"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cycle", "theme"],
                name="unique_cycle_theme"
            )
        ]

    def __str__(self):
        return f"{self.cycle} - {self.theme} (P{self.priority})"


class BaseElo(models.Model):
    elo = models.IntegerField(default=1500)
    puzzles_played = models.PositiveIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def expected_score(self, opponent_elo: int) -> float:
        return 1 / (1 + math.pow(10, (opponent_elo - self.elo) / 400))

    def k_factor(self) -> int:
        if self.puzzles_played < 30:
            return 40
        if self.elo < 2000:
            return 20
        return 10

    def update_elo(self, opponent_elo: int, score: float):
        expected = self.expected_score(opponent_elo)
        k = self.k_factor()

        self.elo = round(self.elo + k * (score - expected))
        self.puzzles_played += 1
        self.save(update_fields=["elo", "puzzles_played", "last_updated"])


class Elo(BaseElo):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="elo"
    )

    def __str__(self):
        return f"{self.user} - Elo {self.elo}"


class ThemeElo(BaseElo):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="theme_elos"
    )
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE)
    last_trained = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Última vez que este tema fue entrenado por el usuario",
        auto_now=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "theme"],
                name="unique_user_theme_elo"
            )
        ]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["theme"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.theme}: {self.elo}"


class PuzzleAttempt(models.Model):
    """
    Historial de puzzles realizados
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="puzzle_attempts"
    )
    puzzle_id = models.CharField(max_length=100)
    solved = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["puzzle_id"]),
        ]


class ActiveExercise(models.Model):
    """
    Puzzle activo (solo uno por usuario)
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="active_exercise"
    )
    puzzle_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)


class RetryPuzzle(models.Model):
    """
    Puzzles fallados que deben repetirse
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="retry_puzzles"
    )
    puzzle_id = models.CharField(max_length=100)
    theme = models.ForeignKey(
        Theme, on_delete=models.SET_NULL, null=True
    )
    fail_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "puzzle_id"],
                name="unique_retry_puzzle"
            )
        ]


class BlitzTacticsSession(models.Model):
    """
    Sesión diaria del modo Blitz Tactics (Puzzle Rush / Puzzle Storm).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blitz_sessions"
    )
    date = models.DateField(default=timezone.now)
    puzzles = models.JSONField(
        help_text="Lista de IDs de puzzles seleccionados (30 puzzles)"
    )
    current_puzzle_index = models.PositiveIntegerField(default=0)
    time_remaining = models.PositiveIntegerField(
        default=180,
        help_text="Tiempo restante en segundos"
    )
    failures = models.PositiveIntegerField(
        default=0,
        help_text="Número de fallos acumulados (máximo 3)"
    )
    completed = models.BooleanField(default=False)
    score = models.PositiveIntegerField(
        default=0,
        help_text="Cantidad de puzzles resueltos"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date"],
                name="unique_user_daily_blitz_session"
            )
        ]
        indexes = [
            models.Index(fields=["user", "date"]),
        ]

    def __str__(self):
        return f"Blitz Tactics - {self.user} - {self.date}"

    @property
    def total_puzzles(self):
        return len(self.puzzles)

    @property
    def is_active(self):
        return not self.completed and self.failures < 3 and self.time_remaining > 0

    def add_time(self, seconds):
        self.time_remaining += seconds
        self.save(update_fields=["time_remaining", "updated_at"])

    def record_success(self):
        self.score += 1
        self.current_puzzle_index += 1
        self.add_time(2)  # incremento de 2 segundos por jugada correcta
        if self.current_puzzle_index >= self.total_puzzles:
            self.completed = True
        self.save(update_fields=["score", "current_puzzle_index", "completed", "updated_at"])

    def record_failure(self):
        self.failures += 1
        self.current_puzzle_index += 1
        if self.failures >= 3:
            self.completed = True
        if self.current_puzzle_index >= self.total_puzzles:
            self.completed = True
        self.save(update_fields=["failures", "current_puzzle_index", "completed", "updated_at"])


class BlitzTacticsAttempt(models.Model):
    """
    Intento individual dentro de una sesión de Blitz Tactics.
    """
    session = models.ForeignKey(
        BlitzTacticsSession,
        on_delete=models.CASCADE,
        related_name="attempts"
    )
    puzzle_id = models.CharField(max_length=100)
    solved = models.BooleanField()
    time_taken = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Tiempo empleado en segundos"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self):
        return f"Attempt {self.puzzle_id} - {'Solved' if self.solved else 'Failed'}"


"""
class TrainingStreak(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="training_streak"
    )
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    last_training_date = models.DateField(null=True, blank=True)
"""
