from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import (ActiveExercise, BlitzTacticsAttempt, BlitzTacticsSession,
                     Document, DocumentCategory, DocumentTag, Elo,
                     EloSnapshot, FreeActiveExercise, FreePuzzleAttempt,
                     PuzzleAttempt, RetryPuzzle, Theme, ThemeCategory,
                     ThemeElo, TrainingCycle, TrainingCycleTheme,
                     TrainingPlanConfig,
                     VisionRushAttempt, VisionRushSession)

User = get_user_model()


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "lichess_name",
    )

    list_filter = (
        "category",
    )

    search_fields = (
        "name",
        "lichess_name",
    )

    ordering = ("category__name", "name")

    autocomplete_fields = ("category",)

    fieldsets = (
        (
            "Información básica",
            {
                "fields": (
                    "name",
                    "description",
                )
            },
        ),
        (
            "Categoría",
            {
                "fields": (
                    "category",
                ),
                "description": (
                    "Categoría a la que pertenece el tema."
                ),
            },
        ),
        (
            "Integración con Lichess",
            {
                "fields": (
                    "lichess_name",
                ),
                "description": (
                    "Nombre del tema en Lichess."
                ),
            },
        ),
    )



    def get_queryset(self, request):
        """
        Optimiza queries en admin (category)
        """
        qs = super().get_queryset(request)
        return qs.select_related("category")


@admin.register(ThemeCategory)
class ThemeCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "lichess_name", "description")
    search_fields = ("name", "lichess_name")
    ordering = ("name",)


class TrainingCycleThemeInline(admin.TabularInline):
    model = TrainingCycleTheme
    extra = 0
    readonly_fields = ("theme",)
    autocomplete_fields = ("theme",)


@admin.register(TrainingCycle)
class TrainingCycleAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "start_date",
        "end_date",
        "total_puzzles",
        "completed_puzzles",
        "created_at",
    )
    list_filter = ("start_date", "end_date")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)
    date_hierarchy = "start_date"

    inlines = [TrainingCycleThemeInline]


@admin.register(TrainingCycleTheme)
class TrainingCycleThemeAdmin(admin.ModelAdmin):
    list_display = ("cycle", "theme")
    list_filter = ("theme",)
    search_fields = (
        "cycle__user__username",
        "cycle__user__email",
        "theme__name",
    )
    autocomplete_fields = ("cycle", "theme")
    list_select_related = ("cycle", "theme")


@admin.register(Elo)
class EloAdmin(admin.ModelAdmin):
    list_display = ("user", "elo", "puzzles_played", "last_updated")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("last_updated",)
    autocomplete_fields = ("user",)


@admin.register(ThemeElo)
class ThemeEloAdmin(admin.ModelAdmin):
    list_display = ("user", "theme", "elo", "puzzles_played", "last_updated")
    list_filter = ("theme",)
    search_fields = ("user__username", "user__email", "theme__name")
    readonly_fields = ("last_updated",)
    autocomplete_fields = ("user", "theme")
    list_select_related = ("user", "theme")


@admin.register(PuzzleAttempt)
class PuzzleAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "puzzle_id",
        "solved",
        "mode",
        "is_retry",
        "created_at",
    )
    list_filter = ("solved", "mode", "created_at")
    search_fields = ("user__username", "puzzle_id")
    readonly_fields = ("created_at", "puzzle_rating", "elo_change")
    autocomplete_fields = ("user", "theme")
    date_hierarchy = "created_at"
    list_select_related = ("user", "theme")


@admin.register(ActiveExercise)
class ActiveExerciseAdmin(admin.ModelAdmin):
    list_display = ("user", "puzzle_id", "created_at")
    search_fields = ("user__username", "puzzle_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)
    list_select_related = ("user",)


@admin.register(RetryPuzzle)
class RetryPuzzleAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "puzzle_id",
        "theme",
        "fail_count",
        "last_attempt_at",
    )
    list_filter = ("theme",)
    search_fields = ("user__username", "puzzle_id")
    readonly_fields = ("last_attempt_at",)
    autocomplete_fields = ("user", "theme")
    list_select_related = ("user", "theme")


@admin.register(DocumentCategory)
class DocumentCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at")
    search_fields = ("name",)


@admin.register(DocumentTag)
class DocumentTagAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "uploaded_by", "created_at", "is_active")
    list_filter = ("category", "is_active", "created_at")
    search_fields = ("title", "description")
    readonly_fields = ("uploaded_by", "created_at")
    autocomplete_fields = ("category", "uploaded_by")
    list_select_related = ("category", "uploaded_by")


@admin.register(FreePuzzleAttempt)
class FreePuzzleAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "puzzle_id",
        "solved",
        "theme_lichess_name",
        "rating_min",
        "rating_max",
        "created_at",
    )
    list_filter = ("solved", "created_at")
    search_fields = ("user__username", "puzzle_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)
    date_hierarchy = "created_at"
    list_select_related = ("user",)


@admin.register(FreeActiveExercise)
class FreeActiveExerciseAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "puzzle_id",
        "theme_lichess_name",
        "rating_min",
        "rating_max",
        "created_at",
    )
    search_fields = ("user__username", "puzzle_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)
    list_select_related = ("user",)


@admin.register(TrainingPlanConfig)
class TrainingPlanConfigAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "is_active",
        "puzzles_per_cycle",
        "themes_per_cycle",
        "theme_selection_mode",
        "blitz_puzzles",
        "vision_exercises",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "theme_selection_mode")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    filter_horizontal = ("selected_themes",)

    fieldsets = (
        (
            "Estado",
            {
                "fields": (
                    "user",
                    "is_active",
                )
            },
        ),
        (
            "Ciclo de entrenamiento",
            {
                "fields": (
                    "puzzles_per_cycle",
                    "themes_per_cycle",
                    "theme_selection_mode",
                    "selected_themes",
                )
            },
        ),
        (
            "Modos de juego",
            {
                "fields": (
                    "blitz_puzzles",
                    "vision_exercises",
                    "blitz_sessions_per_cycle",
                    "vision_sessions_per_cycle",
                )
            },
        ),
        (
            "Metadatos",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )


@admin.register(BlitzTacticsSession)
class BlitzTacticsSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "date",
        "current_puzzle_index",
        "score",
        "failures",
        "time_remaining",
        "completed",
        "created_at",
    )
    list_filter = ("completed", "date")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    date_hierarchy = "date"


@admin.register(BlitzTacticsAttempt)
class BlitzTacticsAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "puzzle_id",
        "solved",
        "time_taken",
        "created_at",
    )
    list_filter = ("solved", "created_at")
    search_fields = (
        "puzzle_id",
        "session__user__username",
    )
    readonly_fields = ("created_at",)
    autocomplete_fields = ("session",)
    date_hierarchy = "created_at"
    list_select_related = ("session", "session__user")


@admin.register(VisionRushSession)
class VisionRushSessionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "date",
        "current_exercise_index",
        "score",
        "failures",
        "completed",
        "created_at",
    )
    list_filter = ("completed", "date")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    date_hierarchy = "date"


@admin.register(VisionRushAttempt)
class VisionRushAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "user_answer",
        "solved",
        "memorization_time",
        "response_time",
        "created_at",
    )
    list_filter = ("solved", "created_at")
    search_fields = (
        "user_answer",
        "session__user__username",
    )
    readonly_fields = ("created_at",)
    autocomplete_fields = ("session",)
    date_hierarchy = "created_at"
    list_select_related = ("session", "session__user")


@admin.register(EloSnapshot)
class EloSnapshotAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "global_elo")
    list_filter = ("date",)
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    date_hierarchy = "date"
    ordering = ("-date",)
