#!/usr/bin/env python3
import sys
import os
import django

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from chess import utils

chesslib = utils.get_chess_lib()

def is_any_check(board):
    """Check if any king is in check."""
    original_turn = board.turn
    board.turn = chesslib.WHITE
    white_check = board.is_check()
    board.turn = chesslib.BLACK
    black_check = board.is_check()
    board.turn = original_turn
    return white_check or black_check

print("Testing generate_random_position for check...")
for i in range(20):
    board = utils.generate_random_position(min_pieces=4, max_pieces=10)
    if is_any_check(board):
        print(f"  ERROR: Position {i+1} has check!")
        print(f"    FEN: {board.fen()}")
        print(f"    Turn: {'white' if board.turn == chesslib.WHITE else 'black'}")
    else:
        print(f"  Position {i+1}: OK (no check)")

print("\nTesting select_vision_rush_exercises...")
class MockUser:
    id = 1

mock_user = MockUser()
exercises = utils.select_vision_rush_exercises(mock_user)
print(f"Generated {len(exercises)} exercises")

check_count = 0
for i, ex in enumerate(exercises):
    board = chesslib.Board(fen=ex['fen'])
    if is_any_check(board):
        check_count += 1
        print(f"  Exercise {i+1} has check!")
        print(f"    FEN: {ex['fen']}")
        print(f"    Question: {ex['question']['text']}")

if check_count == 0:
    print("✓ All exercises free of check")
else:
    print(f"✗ {check_count} exercises have check")

# Also test piece count ranges
print("\nTesting piece count ranges...")
for i, ex in enumerate(exercises):
    board_part = ex['fen'].split()[0]
    piece_count = sum(c.isalpha() for c in board_part)
    if i < 5:
        expected = (4, 6)
    elif i < 10:
        expected = (6, 8)
    else:
        expected = (8, 10)
    
    if not (expected[0] <= piece_count <= expected[1]):
        print(f"  Exercise {i+1} has {piece_count} pieces, expected {expected[0]}-{expected[1]}")
    else:
        print(f"  Exercise {i+1}: {piece_count} pieces ✓")

print("\nDone.")