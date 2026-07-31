from django.urls import path

from . import views

urlpatterns = [
    # Home / Dashboard
    path("", views.home, name="home"),

    # Obtener y mostrar el puzzle actual (GET)
    path("puzzle/", views.get_puzzle, name="get_puzzle"),

    # Enviar resultado del puzzle (POST)
    path("puzzle/submit/", views.submit_puzzle, name="submit_puzzle"),
    path("history/", views.puzzle_history, name="puzzle_history"),
    path("themes/", views.theme_overview, name="theme_overview"),
    path("progress/", views.elo_progress, name="elo_progress"),

    # Blitz Tactics
    path("blitz-tactics/", views.blitz_tactics_start, name="blitz_tactics_start"),
    path("blitz-tactics/new/", views.blitz_tactics_new, name="blitz_tactics_new"),
    path("blitz-tactics/puzzle/", views.blitz_tactics_puzzle,
         name="blitz_tactics_puzzle"),
    path("blitz-tactics/submit/", views.blitz_tactics_submit,
         name="blitz_tactics_submit"),
    path("blitz-tactics/results/<int:session_id>/",
         views.blitz_tactics_results, name="blitz_tactics_results"),
    path("blitz-tactics/history/", views.blitz_tactics_history,
         name="blitz_tactics_history"),

    # Vision Rush
    path("vision-rush/", views.vision_rush_start, name="vision_rush_start"),
    path("vision-rush/new/", views.vision_rush_new, name="vision_rush_new"),
    path("vision-rush/puzzle/", views.vision_rush_puzzle,
         name="vision_rush_puzzle"),
    path("vision-rush/submit/", views.vision_rush_submit,
         name="vision_rush_submit"),
    path("vision-rush/results/<int:session_id>/",
         views.vision_rush_results, name="vision_rush_results"),
    path("vision-rush/history/", views.vision_rush_history,
         name="vision_rush_history"),

    # Entrenamiento libre (no afecta Elo)
    path("free/", views.free_training_start, name="free_training_start"),
    path("free/new/", views.free_training_new, name="free_training_new"),
    path("free/puzzle/", views.free_training_puzzle,
         name="free_training_puzzle"),
    path("free/submit/", views.free_training_submit,
         name="free_training_submit"),
    path("free/skip/", views.free_training_skip, name="free_training_skip"),
    path("free/history/", views.free_training_history,
         name="free_training_history"),
    path("free/retry/<str:puzzle_id>/", views.free_training_retry,
         name="free_training_retry"),

    # Documents
    path("documents/", views.documents_list, name="documents"),
    path("documents/upload/", views.document_upload, name="document_upload"),
    path("documents/<int:document_id>/edit/", views.document_edit, name="document_edit"),
    path("documents/<int:document_id>/delete/",
         views.document_delete, name="document_delete"),
    path("documents/categories/", views.categories_list, name="categories"),
    path("documents/tags/", views.tags_list, name="tags"),

    # Analysis
    path("analysis/", views.analysis, name="analysis"),
]
