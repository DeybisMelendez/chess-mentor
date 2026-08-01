from django import forms

from .models import TrainingPlanConfig


class TrainingPlanConfigForm(forms.ModelForm):
    class Meta:
        model = TrainingPlanConfig
        fields = [
            "is_active",
            "puzzles_per_cycle",
            "themes_per_cycle",
            "theme_selection_mode",
            "selected_themes",
            "blitz_puzzles",
            "vision_exercises",
        ]
        widgets = {
            "selected_themes": forms.CheckboxSelectMultiple(),
        }
