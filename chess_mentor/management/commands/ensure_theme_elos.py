from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from chess_mentor.models import Theme
from chess_mentor.models import ThemeElo


class Command(BaseCommand):
    help = "Ensure that all users have ThemeElo for all themes"

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.all()
        themes = Theme.objects.all()

        created_total = 0

        for user in users:
            missing_themes = themes.exclude(
                themeelo__user=user
            )

            elos = [
                ThemeElo(user=user, theme=theme)
                for theme in missing_themes
            ]

            ThemeElo.objects.bulk_create(
                elos,
                ignore_conflicts=True
            )

            created_total += len(elos)

        self.stdout.write(
            self.style.SUCCESS(
                f"ThemeElo creados: {created_total}"
            )
        )
