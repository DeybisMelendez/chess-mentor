import math
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TrainingPlanConfig(models.Model):
    """
    Configuración personalizada del plan de entrenamiento semanal.
    Se crea bajo demanda; si no existe, se usan los defaults de la plataforma.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="training_plan_config"
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Activar para usar configuración personalizada en lugar de los defaults"
    )

    puzzles_per_cycle = models.PositiveIntegerField(default=100)
    themes_per_cycle = models.PositiveIntegerField(default=10)

    theme_selection_mode = models.CharField(
        max_length=20,
        choices=[
            ("weakest", "Más débiles"),
            ("custom", "Personalizado"),
        ],
        default="weakest",
        help_text="Modo de selección de temas para el ciclo"
    )
    selected_themes = models.ManyToManyField(
        "Theme",
        blank=True,
        help_text="Temas seleccionados (solo usado en modo Personalizado)"
    )

    blitz_puzzles = models.PositiveIntegerField(
        default=30,
        help_text="Cantidad de puzzles por sesión de Blitz Tactics"
    )
    vision_exercises = models.PositiveIntegerField(
        default=15,
        help_text="Cantidad de ejercicios por sesión de Vision Rush"
    )
    blitz_sessions_per_cycle = models.PositiveIntegerField(
        default=5,
        help_text="Sesiones esperadas de Blitz Tactics por ciclo"
    )
    vision_sessions_per_cycle = models.PositiveIntegerField(
        default=5,
        help_text="Sesiones esperadas de Vision Rush por ciclo"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        status = "Activo" if self.is_active else "Inactivo"
        return f"Plan - {self.user} ({status})"


class ThemeCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    lichess_name = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        help_text="Nombre de la categoría en Lichess (opening/middlegame/endgame/mate)"
    )
    description = models.TextField(
        blank=True,
        help_text="Descripción de la categoría"
    )

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Theme categories"

    def __str__(self):
        return self.name


class Theme(models.Model):
    name = models.CharField(max_length=100, unique=True)
    lichess_name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Nombre del tema en Lichess"
    )

    category = models.ForeignKey(
        ThemeCategory,
        on_delete=models.CASCADE,
        related_name="themes",
        help_text="Categoría a la que pertenece el tema"
    )

    description = models.TextField(
        blank=True,
        help_text="Descripción del tema"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        if self.category:
            return f"{self.category.name} → {self.name}"
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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cycle", "theme"],
                name="unique_cycle_theme"
            )
        ]

    def __str__(self):
        return f"{self.cycle} - {self.theme}"


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

    theme = models.ForeignKey(
        Theme,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Tema del puzzle"
    )
    puzzle_rating = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Rating Lichess del puzzle"
    )
    elo_change = models.IntegerField(
        null=True,
        blank=True,
        help_text="Cambio de Elo general tras este intento"
    )
    mode = models.CharField(
        max_length=10,
        choices=[
            ("cycle", "Ciclo"),
            ("blitz", "Blitz"),
        ],
        default="cycle",
        help_text="Modo de entrenamiento en que se realizó"
    )
    is_retry = models.BooleanField(
        default=False,
        help_text="Si fue un puzzle reintentado"
    )

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["puzzle_id"]),
            models.Index(fields=["user", "mode", "created_at"]),
            models.Index(fields=["user", "theme", "created_at"]),
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


class FreePuzzleAttempt(models.Model):
    """
    Historial de puzzles realizados en el modo de entrenamiento libre.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="free_puzzle_attempts"
    )
    puzzle_id = models.CharField(max_length=100)
    solved = models.BooleanField()
    theme_lichess_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Tema seleccionado al momento del intento"
    )
    rating_min = models.PositiveIntegerField(
        help_text="Rating mínimo del rango de dificultad"
    )
    rating_max = models.PositiveIntegerField(
        help_text="Rating máximo del rango de dificultad"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["puzzle_id"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Free - {self.user} - {self.puzzle_id} - {'OK' if self.solved else 'FAIL'}"


class FreeActiveExercise(models.Model):
    """
    Puzzle activo del modo de entrenamiento libre (no afecta el Elo).

    Se diferencia de ``ActiveExercise`` para no interferir con el ciclo
    semanal. Solo puede existir uno por usuario.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="free_active_exercise"
    )
    puzzle_id = models.CharField(max_length=100)
    theme_lichess_name = models.CharField(
        max_length=100,
        help_text="Tema elegido (lichess_name) para obtener nuevos puzzles"
    )
    rating_min = models.PositiveIntegerField()
    rating_max = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Free - {self.user} - {self.puzzle_id}"


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
        self.add_time(2)
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


class VisionRushSession(models.Model):
    """
    Sesión diaria del modo Vision Rush.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="vision_rush_sessions"
    )
    date = models.DateField(default=timezone.now)
    exercises = models.JSONField(
        help_text="Lista de ejercicios seleccionados (15 ejercicios)"
    )
    current_exercise_index = models.PositiveIntegerField(default=0)
    failures = models.PositiveIntegerField(
        default=0,
        help_text="Número de fallos acumulados"
    )
    completed = models.BooleanField(default=False)
    score = models.PositiveIntegerField(
        default=0,
        help_text="Cantidad de ejercicios resueltos"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "date"]),
        ]

    def __str__(self):
        return f"Vision Rush - {self.user} - {self.date}"

    @property
    def total_exercises(self):
        return len(self.exercises)

    @property
    def is_active(self):
        return not self.completed and self.failures < 3

    def record_success(self):
        self.score += 1
        self.current_exercise_index += 1
        if self.current_exercise_index >= self.total_exercises:
            self.completed = True
        self.save(update_fields=["score", "current_exercise_index", "completed", "updated_at"])

    def record_failure(self):
        self.failures += 1
        self.current_exercise_index += 1
        if self.failures >= 3:
            self.completed = True
        if self.current_exercise_index >= self.total_exercises:
            self.completed = True
        self.save(update_fields=["failures", "current_exercise_index", "completed", "updated_at"])


class VisionRushAttempt(models.Model):
    """
    Intento individual dentro de una sesión de Vision Rush.
    """
    session = models.ForeignKey(
        VisionRushSession,
        on_delete=models.CASCADE,
        related_name="attempts"
    )
    exercise_data = models.JSONField(
        help_text="Datos del ejercicio (fen, pregunta, respuesta correcta)"
    )
    user_answer = models.CharField(
        max_length=100,
        help_text="Respuesta proporcionada por el usuario"
    )
    solved = models.BooleanField()
    memorization_time = models.FloatField(
        null=True,
        blank=True,
        help_text="Tiempo de memorización en segundos"
    )
    response_time = models.FloatField(
        null=True,
        blank=True,
        help_text="Tiempo de respuesta en segundos"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self):
        return f"Vision Rush Attempt - {'Solved' if self.solved else 'Failed'}"


class EloSnapshot(models.Model):
    """
    Snapshot diario del Elo global y por tema del usuario.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="elo_snapshots"
    )
    date = models.DateField()
    global_elo = models.IntegerField()
    theme_elos = models.JSONField(
        help_text="Diccionario {theme_name: elo_value} con el Elo de cada tema"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date"],
                name="unique_user_date_snapshot"
            )
        ]
        ordering = ["-date"]

    def __str__(self):
        return f"{self.user} - {self.date} - Elo {self.global_elo}"


def validate_pdf_extension(value):
    ext = os.path.splitext(value.name)[1].lower()
    if ext != '.pdf':
        raise ValidationError('Solo se permiten archivos PDF.')


class DocumentCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'categoría de documento'
        verbose_name_plural = 'categorías de documentos'
        ordering = ('name',)

    def __str__(self):
        return self.name


class DocumentTag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'etiqueta de documento'
        verbose_name_plural = 'etiquetas de documentos'
        ordering = ('name',)

    def __str__(self):
        return self.name


class Document(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        DocumentCategory,
        on_delete=models.PROTECT,
        related_name='documents'
    )
    tags = models.ManyToManyField(
        DocumentTag,
        related_name='documents',
        blank=True
    )
    file = models.FileField(
        upload_to='documents/%Y/%m/',
        validators=[validate_pdf_extension]
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='uploaded_documents'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'documento'
        verbose_name_plural = 'documentos'
        ordering = ('-created_at',)

    def __str__(self):
        return self.title

    def delete(self, using=None, keep_parents=False):
        if self.file:
            self.file.delete()
        super().delete(using, keep_parents)