from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import (ActiveExercise, Elo, PuzzleAttempt, RetryPuzzle, Theme,
                     ThemeCategory, ThemeElo, TrainingCycle, TrainingCycleTheme,
                     TrainingPreferences)

User = get_user_model()


@admin.register(TrainingPreferences)
class TrainingPreferencesAdmin(admin.ModelAdmin):
    list_display = ("user", "puzzles_per_cycle")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)


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
    readonly_fields = ("theme", "priority")
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
    list_display = ("cycle", "theme", "priority")
    list_filter = ("priority", "theme")
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
        "created_at",
    )
    list_filter = ("solved",  "created_at")
    search_fields = ("user__username", "puzzle_id")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("user",)
    date_hierarchy = "created_at"
    list_select_related = ("user",)


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
