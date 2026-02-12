from django.core.management.base import BaseCommand
from django.db import transaction
import re
from chess_mentor.models import Theme
from chess_mentor.repository import LichessDB


class Command(BaseCommand):
    help = "Sincroniza los temas de Django con los temas de lichess_puzzles.sqlite3"

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
            self.stdout.write(self.style.WARNING("MODO DRY RUN - No se realizarán cambios"))
        if force:
            self.stdout.write(self.style.WARNING("MODO FORCE - Se eliminarán temas incluso con dependencias"))
        
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

        self.stdout.write(f"Temas en lichess_puzzles.sqlite3: {len(lichess_theme_names)}")

        # Obtener categorías padre (temas no entrenables)
        parent_categories = Theme.objects.filter(is_trainable=False)
        parent_by_lichess_name = {cat.lichess_name: cat for cat in parent_categories}

        # Crear categorías padre si faltan
        required_parents = ["opening", "middlegame", "endgame", "mate"]
        for parent_name in required_parents:
            if parent_name not in parent_by_lichess_name:
                # Crear categoría padre
                display_name = {
                    "opening": "Apertura",
                    "middlegame": "Mediojuego",
                    "endgame": "Finales",
                    "mate": "Jaque mate",
                }.get(parent_name, parent_name.capitalize())
                
                if dry_run:
                    self.stdout.write(f"[DRY RUN] Se crearía categoría padre: {display_name} ({parent_name})")
                    # Crear objeto simulado para continuar
                    parent = Theme(
                        name=display_name,
                        lichess_name=parent_name,
                        is_trainable=False,
                    )
                else:
                    parent = Theme.objects.create(
                        name=display_name,
                        lichess_name=parent_name,
                        is_trainable=False,
                    )
                parent_by_lichess_name[parent_name] = parent

        # Mapear cada tema a su categoría padre
        theme_to_parent = {}
        category_counts = {"endgame": 0, "mate": 0, "opening": 0, "middlegame": 0}
        
        for theme_name in lichess_theme_names:
            if theme_name in ["opening", "middlegame", "endgame", "mate"]:
                # Estos son categorías padre, no temas entrenables
                continue
            
            # Determinar categoría padre basada en reglas
            if "Endgame" in theme_name or theme_name in ["pawnEndgame", "rookEndgame", 
                                                         "bishopEndgame", "knightEndgame", 
                                                         "queenEndgame", "bishopPair",
                                                         "oppositeColoredBishops", "sameColoredBishops"]:
                parent_name = "endgame"
            elif theme_name.startswith("mateIn"):
                parent_name = "mate"
            elif "Mate" in theme_name:
                parent_name = "mate"
            elif theme_name == "opening":
                parent_name = "opening"
            else:
                # Por defecto, mediojuego
                parent_name = "middlegame"
            
            theme_to_parent[theme_name] = parent_by_lichess_name.get(parent_name)
            category_counts[parent_name] += 1
        
        self.stdout.write(f"Distribución de temas entrenables: {category_counts}")

        # Sincronizar temas entrenables
        created = 0
        updated = 0
        for lichess_name in lichess_theme_names:
            if lichess_name in ["opening", "middlegame", "endgame", "mate"]:
                continue
            
            parent = theme_to_parent.get(lichess_name)
            if not parent:
                self.stderr.write(f"Advertencia: No se encontró padre para {lichess_name}, se omitirá.")
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
                if theme.parent != parent and theme.is_trainable:
                    if dry_run:
                        self.stdout.write(f"[DRY RUN] Se actualizaría padre de {theme.name} -> {parent.name}")
                    else:
                        theme.parent = parent
                        theme.save()
                        self.stdout.write(f"Actualizado padre de {theme.name} -> {parent.name}")
                    updated += 1
                    
            except Theme.DoesNotExist:
                # Tema no existe, crearlo
                if dry_run:
                    self.stdout.write(f"[DRY RUN] Se crearía tema: {display_name} ({lichess_name})")
                else:
                    theme = Theme.objects.create(
                        name=display_name,
                        lichess_name=lichess_name,
                        parent=parent,
                        is_trainable=True,
                    )
                    self.stdout.write(f"Creado tema: {display_name} ({lichess_name})")
                created += 1

        # Eliminar temas entrenables que ya no existen en lichess_puzzles.sqlite3
        deleted = 0
        django_trainable_themes = Theme.objects.filter(
            is_trainable=True,
            lichess_name__isnull=False
        ).exclude(
            lichess_name__in=["opening", "middlegame", "endgame", "mate"]  # Excluir categorías padre
        )
        
        skipped = 0
        for theme in django_trainable_themes:
            if theme.lichess_name not in lichess_theme_names:
                theme_name = theme.name
                
                # Verificar si el tema tiene dependencias
                has_theme_elo = ThemeElo.objects.filter(theme=theme).exists()
                has_training_cycle = TrainingCycleTheme.objects.filter(theme=theme).exists()
                has_retry_puzzle = RetryPuzzle.objects.filter(theme=theme).exists()
                
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
                        theme_elo_count = ThemeElo.objects.filter(theme=theme).count()
                        self.stdout.write(f"[DRY RUN] Se eliminaría tema '{theme_name}' y sus {theme_elo_count} registros ThemeElo")
                    else:
                        # Eliminar todos los ThemeElo asociados primero
                        theme_elos_deleted, _ = ThemeElo.objects.filter(theme=theme).delete()
                        theme.delete()
                        self.stdout.write(f"Eliminado tema '{theme_name}' y {theme_elos_deleted} registros ThemeElo asociados")
                    deleted += 1
                    continue  # Ya se eliminó, continuar al siguiente tema
                
                if dry_run:
                    self.stdout.write(f"[DRY RUN] Se eliminaría tema: {theme_name} ({theme.lichess_name})")
                else:
                    theme.delete()
                    self.stdout.write(f"Eliminado tema: {theme_name} ({theme.lichess_name})")
                deleted += 1

        self.stdout.write(self.style.SUCCESS(
            f"Sincronización completada. Creados: {created}, Actualizados: {updated}, Eliminados: {deleted}, Omitidos: {skipped}"
        ))