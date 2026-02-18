from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import (Elo, Theme, ThemeElo, TrainingCycle, TrainingCycleTheme,
                     TrainingPreferences)

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

    theme_elos = (
        ThemeElo.objects
        .filter(
            user=instance.user
        )
        .select_related("theme")
    )

    if theme_elos.count() < 1:
        return

    weak_themes = theme_elos.order_by("elo", "theme_id")[:3]
    weak_theme_ids = weak_themes.values_list("theme_id", flat=True)

    objs = [
        TrainingCycleTheme(
            cycle=instance,
            theme=theme_elo.theme,
            priority=priority
        )
        for priority, theme_elo in enumerate(weak_themes, start=1)
    ]

    TrainingCycleTheme.objects.bulk_create(objs)
