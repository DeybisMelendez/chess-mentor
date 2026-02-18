from django.core.management.base import BaseCommand
from django.db import transaction
import re
from chess_mentor.models import Theme, ThemeCategory
from chess_mentor.repository import LichessDB


class Command(BaseCommand):
    help = "Sincroniza los temas de Django con los temas de lichess_puzzles.sqlite3"

    # Temas de ajedrez definidos en import_lichess_puzzles.py
    CHESS_THEMES = {
        # Mediojuego
        "fork", "pin", "skewer", "discoveredAttack", "doubleCheck",
        "deflection", "decoy", "interference", "zugzwang",
        "sacrifice", "clearance", "xRayAttack", "windmill",
        "annihilation", "capturingDefender", "hangingPiece",
        "attraction", "discoveredCheck", "intermezzo", "quietMove",
        "defensiveMove", "advancedPawn", "promotion", "enPassant",
        "castling", "underPromotion", "trappedPiece", "exposedKing",
        "attackingF2F7", "equality", "kingsideAttack", "queensideAttack",

        # Jaque mate
        "backRankMate", "smotheredMate", "arabianMate", "hookMate",
        "pillsburysMate", "operaMate", "cornerMate", "anastasiaMate",
        "morphysMate", "triangleMate", "blindSwineMate", "killBoxMate",
        "dovetailMate", "bodenMate", "doubleBishopMate", "vukovicMate",
        "balestraMate", "epauletteMate", "hookMate", "swallowstailMate",

        # Finales
        "endgame", "pawnEndgame", "rookEndgame", "bishopEndgame", "knightEndgame",
        "queenEndgame", "queenRookEndgame"
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Muestra lo que se haría sin realizar cambios",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            dest="force",
            help="Eliminar temas incluso si tienen dependencias",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        force = options.get("force", False)

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "MODO DRY RUN - No se realizarán cambios"))
        if force:
            self.stdout.write(self.style.WARNING(
                "MODO FORCE - Se eliminarán temas incluso con dependencias"))

        self.stdout.write("Iniciando sincronización de temas...")

        # Usar transacción solo si no es dry-run
        if dry_run:
            # En dry-run, ejecutar sin transacción pero sin guardar cambios
            self._sync_themes(dry_run=True, force=force)
        else:
            with transaction.atomic():
                self._sync_themes(dry_run=False, force=force)

    def _sync_themes(self, dry_run=False, force=False):
        from chess_mentor.models import ThemeElo, TrainingCycleTheme, RetryPuzzle

        # Obtener todos los temas de lichess_puzzles.sqlite3
        lichess_db = LichessDB()
        conn = lichess_db.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM themes ORDER BY name")
        lichess_theme_names = {row[0] for row in cursor.fetchall()}

        self.stdout.write(
            f"Temas en lichess_puzzles.sqlite3: {len(lichess_theme_names)}")

        # Filtrar solo temas definidos en CHESS_THEMES (excluyendo categorías)
        chess_themes = self.CHESS_THEMES
        filtered_theme_names = {
            name for name in lichess_theme_names if name in chess_themes}
        self.stdout.write(
            f"Temas filtrados (CHESS_THEMES): {len(filtered_theme_names)}")
        if len(lichess_theme_names) - len(filtered_theme_names) > 0:
            excluded = lichess_theme_names - filtered_theme_names
            self.stdout.write(
                f"Temas excluidos (no en CHESS_THEMES): {len(excluded)}")
            for theme in sorted(excluded):
                self.stdout.write(f"  - {theme}")

        # Usar solo temas filtrados para sincronización
        lichess_theme_names = filtered_theme_names

        # Obtener categorías (ThemeCategory)
        categories = ThemeCategory.objects.all()
        category_by_lichess_name = {
            cat.lichess_name: cat for cat in categories}

        # Crear categorías si faltan
        required_categories = ["opening", "middlegame", "endgame", "mate"]
        for cat_name in required_categories:
            if cat_name not in category_by_lichess_name:
                # Crear categoría
                display_name = {
                    "opening": "Apertura",
                    "middlegame": "Mediojuego",
                    "endgame": "Finales",
                    "mate": "Jaque mate",
                }.get(cat_name, cat_name.capitalize())

                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Se crearía categoría: {display_name} ({cat_name})")
                    # Crear objeto simulado para continuar
                    category = ThemeCategory(
                        name=display_name,
                        lichess_name=cat_name,
                    )
                else:
                    category = ThemeCategory.objects.create(
                        name=display_name,
                        lichess_name=cat_name,
                    )
                category_by_lichess_name[cat_name] = category

        # Mapear cada tema a su categoría
        theme_to_category = {}
        category_counts = {"endgame": 0, "mate": 0,
                           "opening": 0, "middlegame": 0}

        for theme_name in lichess_theme_names:
            if theme_name in ["opening", "middlegame", "endgame", "mate"]:
                # Estos son categorías, no temas entrenables
                continue

            # Determinar categoría basada en reglas
            if "Endgame" in theme_name or theme_name in ["pawnEndgame", "rookEndgame",
                                                         "bishopEndgame", "knightEndgame",
                                                         "queenEndgame", "queenRookEndgame"]:
                category_name = "endgame"
            elif theme_name.startswith("mateIn"):
                category_name = "mate"
            elif "Mate" in theme_name:
                category_name = "mate"
            elif theme_name == "opening":
                category_name = "opening"
            else:
                # Por defecto, mediojuego
                category_name = "middlegame"

            theme_to_category[theme_name] = category_by_lichess_name.get(
                category_name)
            category_counts[category_name] += 1

        self.stdout.write(
            f"Distribución de temas entrenables: {category_counts}")

        # Sincronizar temas entrenables
        created = 0
        updated = 0
        for lichess_name in lichess_theme_names:
            if lichess_name in ["opening", "middlegame", "endgame", "mate"]:
                continue

            category = theme_to_category.get(lichess_name)
            if not category:
                self.stderr.write(
                    f"Advertencia: No se encontró categoría para {lichess_name}, se omitirá.")
                continue

            # Generar nombre legible (capitalize, separar palabras) solo para nuevos
            display_name = lichess_name
            display_name = re.sub(r'([a-z])([A-Z])', r'\1 \2', display_name)
            display_name = display_name.capitalize()

            # Buscar tema existente por lichess_name
            try:
                # Tema existe
                theme = Theme.objects.get(lichess_name=lichess_name)

                # Verificar si necesita actualización
                if theme.category != category:
                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] Se actualizaría categoría de {theme.name} -> {category.name}")
                    else:
                        theme.category = category
                        theme.save()
                        self.stdout.write(
                            f"Actualizado categoría de {theme.name} -> {category.name}")
                    updated += 1

            except Theme.DoesNotExist:
                # Tema no existe, crearlo
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Se crearía tema: {display_name} ({lichess_name})")
                else:
                    theme = Theme.objects.create(
                        name=display_name,
                        lichess_name=lichess_name,
                        category=category,
                    )
                    self.stdout.write(
                        f"Creado tema: {display_name} ({lichess_name})")
                created += 1

        # Eliminar temas entrenables que ya no existen en lichess_puzzles.sqlite3
        deleted = 0
        django_trainable_themes = Theme.objects.filter(
            lichess_name__isnull=False
        ).exclude(
            lichess_name__in=["opening", "middlegame",
                              "endgame", "mate"]  # Excluir categorías
        )

        skipped = 0
        for theme in django_trainable_themes:
            if theme.lichess_name not in lichess_theme_names:
                theme_name = theme.name

                # Verificar si el tema tiene dependencias
                has_theme_elo = ThemeElo.objects.filter(theme=theme).exists()
                has_training_cycle = TrainingCycleTheme.objects.filter(
                    theme=theme).exists()
                has_retry_puzzle = RetryPuzzle.objects.filter(
                    theme=theme).exists()

                has_other_dependencies = has_training_cycle
                has_only_theme_elo = has_theme_elo and not has_other_dependencies

                dependency_info = []
                if has_theme_elo:
                    dependency_info.append("ThemeElo")
                if has_training_cycle:
                    dependency_info.append("TrainingCycleTheme")
                if has_retry_puzzle:
                    dependency_info.append("RetryPuzzle")

                # Si tiene dependencias que no sean solo ThemeElo
                if has_other_dependencies:
                    if not force:
                        self.stderr.write(
                            f"Advertencia: No se eliminará el tema '{theme_name}' porque tiene dependencias críticas: {', '.join(dependency_info)}"
                        )
                        skipped += 1
                        continue
                    else:
                        self.stdout.write(
                            f"Advertencia: El tema '{theme_name}' tiene dependencias críticas ({', '.join(dependency_info)}) pero se eliminará debido a --force"
                        )

                # Si solo tiene ThemeElo, eliminarlo junto con sus ThemeElo
                elif has_only_theme_elo:
                    if dry_run:
                        theme_elo_count = ThemeElo.objects.filter(
                            theme=theme).count()
                        self.stdout.write(
                            f"[DRY RUN] Se eliminaría tema '{theme_name}' y sus {theme_elo_count} registros ThemeElo")
                    else:
                        # Eliminar todos los ThemeElo asociados primero
                        theme_elos_deleted, _ = ThemeElo.objects.filter(
                            theme=theme).delete()
                        theme.delete()
                        self.stdout.write(
                            f"Eliminado tema '{theme_name}' y {theme_elos_deleted} registros ThemeElo asociados")
                    deleted += 1
                    continue  # Ya se eliminó, continuar al siguiente tema

                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Se eliminaría tema: {theme_name} ({theme.lichess_name})")
                else:
                    theme.delete()
                    self.stdout.write(
                        f"Eliminado tema: {theme_name} ({theme.lichess_name})")
                deleted += 1

        self.stdout.write(self.style.SUCCESS(
            f"Sincronización completada. Creados: {created}, Actualizados: {updated}, Eliminados: {deleted}, Omitidos: {skipped}"
        ))
