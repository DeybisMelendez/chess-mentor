#!/usr/bin/env python
"""
Prueba rápida del template blitz_tactics_puzzle.html
"""
import os
import sys
import django
from django.template import Template, Context
from django.conf import settings

# Configurar Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

# Cargar template
template_path = "chess/templates/blitz_tactics_puzzle.html"
with open(template_path, "r") as f:
    template_content = f.read()

template = Template(template_content)

# Contexto de prueba
context = Context({
    "current_puzzle": 5,
    "total_puzzles": 30,
    "failures": 1,
    "time_remaining": 150,
    "session": type('obj', (object,), {
        'id': 1,
        'date': '2025-01-28',
    }),
    "puzzle": {
        "puzzle_id": "test123",
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "moves": ["e2e4", "e7e5"],
        "orientation": "white",
    },
    "csrf_token": "testtoken",
})

# Renderizar
try:
    output = template.render(context)
    print("✅ Template renderizado exitosamente")
    # Verificar elementos clave en el output
    if "Blitz Tactics" in output:
        print("✅ Contiene 'Blitz Tactics'")
    if '<span id="timer">' in output:
        print("✅ Contiene temporizador")
    if '<p id="status"' in output:
        print("✅ Contiene elemento status")
    if 'chess-board' in output:
        print("✅ Contiene chess-board")
    print("\nTemplate parece correcto.")
except Exception as e:
    print(f"❌ Error renderizando template: {e}")
    import traceback
    traceback.print_exc()