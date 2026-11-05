https://github.com/bb0i4/

SIMPLE CHESS  -  for Windows 11
=================================

HOW TO GET THE .EXE  (one time, about 2 minutes)
-------------------------------------------------
1. Install Python 3 from https://www.python.org/downloads/
   During setup, tick "Add python.exe to PATH".
2. Double-click  build_exe.bat  in this folder.
   (It downloads the packaging tool once, so it needs internet only this one time.)
3. When it finishes, SimpleChess.exe appears in this folder.
   Copy it anywhere you like. It is a single file, needs no installation,
   and works completely offline.

Quick test without building:  double-click chess_app.py  (or run: py chess_app.py)

HOW TO PLAY
-----------
* Click a piece, then click where it should go.
* New Game: choose "Myself" (two players) or "The computer",
  your colour, and the difficulty (Beginner / Easy / Medium / Hard).
* Undo Move: takes back your last move (and the computer's reply).
* Flip Board: turns the board around.
* Shortcuts: Ctrl+N new game, Ctrl+Z undo, F flip board.

SETTINGS
--------
* Flip the board after every move (two-player mode)   <- default ON
* Show possible moves for the selected piece
* Highlight the last move
* Show board coordinates (a-h, 1-8)
* Always promote pawns to a queen (otherwise you are asked)
* Board colours (4 themes)
* Computer difficulty
Settings are saved automatically in %APPDATA%\SimpleChess\settings.json

RULES SUPPORTED
---------------
Castling, en passant, pawn promotion, check, checkmate, stalemate,
threefold repetition, 50-move rule, and insufficient material.

NOTE
----
Windows SmartScreen may say "unknown publisher" the first time you run a
self-built .exe. Click "More info" then "Run anyway". This happens to any
program that is not code-signed; the source code is chess_app.py.
