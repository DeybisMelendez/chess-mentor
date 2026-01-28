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
    
    # Blitz Tactics
    path("blitz-tactics/", views.blitz_tactics_start, name="blitz_tactics_start"),
    path("blitz-tactics/new/", views.blitz_tactics_new, name="blitz_tactics_new"),
    path("blitz-tactics/puzzle/", views.blitz_tactics_puzzle, name="blitz_tactics_puzzle"),
    path("blitz-tactics/submit/", views.blitz_tactics_submit, name="blitz_tactics_submit"),
    path("blitz-tactics/results/<int:session_id>/", views.blitz_tactics_results, name="blitz_tactics_results"),
    path("blitz-tactics/history/", views.blitz_tactics_history, name="blitz_tactics_history"),
]
