#!/usr/bin/env python3
import sys
import os
import django

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from chess_mentor import utils

class MockUser:
    id = 1

mock_user = MockUser()
exercises = utils.select_vision_rush_exercises(mock_user)

print("=== Checking Spanish piece names in questions ===")
for i, ex in enumerate(exercises[:8]):
    print(f"\nExercise {i+1}:")
    print(f"  Type: {ex['question']['type']}")
    print(f"  Text: {ex['question']['text']}")
    if 'piece' in ex['question']:
        print(f"  Piece symbol: {ex['question']['piece']}")
    
    # Check for remaining symbols
    for symbol in ['P', 'N', 'B', 'R', 'Q', 'K']:
        if symbol in ex['question']['text']:
            print(f"  ⚠ Contains symbol {symbol}!")
    
    # Check Spanish words
    spanish_pieces = ['peón', 'caballo', 'alfil', 'torre', 'dama', 'rey']
    for word in spanish_pieces:
        if word in ex['question']['text'].lower():
            print(f"  ✓ Contains '{word}'")

print("\n=== Summary ===")
symbol_count = 0
spanish_count = 0
for ex in exercises:
    text = ex['question']['text']
    for symbol in ['P', 'N', 'B', 'R', 'Q', 'K']:
        if symbol in text:
            symbol_count += 1
            break
    for word in ['peón', 'caballo', 'alfil', 'torre', 'dama', 'rey']:
        if word in text.lower():
            spanish_count += 1
            break

print(f"Questions with symbols: {symbol_count}/15")
print(f"Questions with Spanish names: {spanish_count}/15")
if symbol_count == 0 and spanish_count > 0:
    print("✓ All questions use Spanish names correctly")
else:
    print("⚠ Some questions may still use symbols")