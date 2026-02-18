# Generated manually
import django.db.models.deletion
from django.db import migrations, models


def ensure_no_null_category(apps, schema_editor):
    Theme = apps.get_model('chess', 'Theme')
    # Check for themes with null category
    null_count = Theme.objects.filter(category__isnull=True).count()
    if null_count > 0:
        # Assign default category (first category)
        ThemeCategory = apps.get_model('chess', 'ThemeCategory')
        default_category = ThemeCategory.objects.first()
        if default_category:
            Theme.objects.filter(category__isnull=True).update(category=default_category)
        else:
            # Create a default category if none exists
            default_category = ThemeCategory.objects.create(
                name="Default",
                lichess_name="default",
                description="Default category"
            )
            Theme.objects.filter(category__isnull=True).update(category=default_category)


def ensure_no_null_lichess_name(apps, schema_editor):
    Theme = apps.get_model('chess', 'Theme')
    # Check for themes with null lichess_name
    null_count = Theme.objects.filter(lichess_name__isnull=True).count()
    if null_count > 0:
        # Set lichess_name to name if null
        for theme in Theme.objects.filter(lichess_name__isnull=True):
            theme.lichess_name = theme.name
            theme.save()


class Migration(migrations.Migration):

    dependencies = [
        ('chess', '0018_themecategory_remove_theme_parent_theme_category'),
    ]

    operations = [
        # Ensure no null categories before making field non-nullable
        migrations.RunPython(ensure_no_null_category, migrations.RunPython.noop),
        # Ensure no null lichess_name before making field non-nullable
        migrations.RunPython(ensure_no_null_lichess_name, migrations.RunPython.noop),
        # Remove is_trainable field
        migrations.RemoveField(
            model_name='theme',
            name='is_trainable',
        ),
        # Alter category field to non-nullable
        migrations.AlterField(
            model_name='theme',
            name='category',
            field=models.ForeignKey(
                help_text='Categoría a la que pertenece el tema',
                on_delete=django.db.models.deletion.CASCADE,
                related_name='themes',
                to='chess.themecategory',
            ),
        ),
        # Alter lichess_name field to non-nullable
        migrations.AlterField(
            model_name='theme',
            name='lichess_name',
            field=models.CharField(
                help_text='Nombre del tema en Lichess',
                max_length=100,
                unique=True,
            ),
        ),
        # Alter description field (help text only)
        migrations.AlterField(
            model_name='theme',
            name='description',
            field=models.TextField(
                blank=True,
                help_text='Descripción del tema',
            ),
        ),
    ]