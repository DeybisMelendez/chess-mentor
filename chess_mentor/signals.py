from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import (Elo, Theme, ThemeElo, TrainingCycle, TrainingCycleTheme,
                     TrainingPlanConfig, TrainingPreferences)

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_training_base(sender, instance, created, **kwargs):
    if not created:
        return

    TrainingPreferences.objects.get_or_create(user=instance)
    Elo.objects.get_or_create(user=instance)

    themes = Theme.objects.all()
    if not themes.exists():
        return

    ThemeElo.objects.bulk_create(
        [
            ThemeElo(user=instance, theme=theme)
            for theme in themes
        ],
        ignore_conflicts=True
    )


@receiver(post_save, sender=Theme)
def create_theme_elos_for_all_users(sender, instance, created, **kwargs):
    if not created:
        return

    users = User.objects.all()
    if not users.exists():
        return

    ThemeElo.objects.bulk_create(
        [
            ThemeElo(user=user, theme=instance)
            for user in users
        ],
        ignore_conflicts=True
    )


@receiver(post_save, sender=TrainingCycle)
@transaction.atomic
def assign_cycle_themes(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.themes.exists():
        return

    config = TrainingPlanConfig.objects.filter(
        user=instance.user,
        is_active=True
    ).first()

    limit = config.themes_per_cycle if config else 10
    mode = config.theme_selection_mode if config else "weakest"

    theme_elos = (
        ThemeElo.objects
        .filter(user=instance.user)
        .select_related("theme")
    )

    if theme_elos.count() < 1:
        return

    if mode == "custom" and config:
        selected = list(config.selected_themes.all())
        if selected:
            objs = [
                TrainingCycleTheme(cycle=instance, theme=theme)
                for theme in selected
            ]
        else:
            # Fallback: si no hay temas seleccionados, usar weakest
            weak_themes = theme_elos.order_by("elo", "theme_id")[:limit]
            objs = [
                TrainingCycleTheme(cycle=instance, theme=te.theme)
                for te in weak_themes
            ]
    else:
        weak_themes = theme_elos.order_by("elo", "theme_id")[:limit]
        objs = [
            TrainingCycleTheme(cycle=instance, theme=te.theme)
            for te in weak_themes
        ]

    TrainingCycleTheme.objects.bulk_create(objs)
