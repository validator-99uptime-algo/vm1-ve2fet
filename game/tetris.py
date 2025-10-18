#!/usr/bin/env python3
"""Terminal‑Tetris (curses)
   • Arrow / A‑D: move    • W / ↑: rotate    • S / ↓: soft‑drop
   • Space: hard drop     • Q: quit

   Pieces now spawn two rows *above* the visible well so the game
   doesn’t end the instant blocks touch the ceiling.
"""

import curses, random, time

# ─────────────────────────── Constants ────────────────────────────────────
BOARD_W, BOARD_H = 10, 20     # play‑field size in cells
SPAWN_ROW        = -2         # spawn piece this many rows above the board
GRAVITY_MS_START = 500        # milliseconds between falls at level 0
LVL_UP_EVERY     = 10         # lines per level
SOFT_DROP_MS     = 40         # soft‑drop interval when ↓ is held
MIN_GRAVITY_MS   = 100        # cap so it never gets too fast

# Tetromino rotation states (row, col) offsets
PIECES = {
    "I": [ [(0,-1),(0,0),(0,1),(0,2)], [(-1,0),(0,0),(1,0),(2,0)] ],
    "J": [ [(0,-1),(0,0),(0,1),(1,1)],  [(-1,0),(0,0),(1,0),(1,-1)],
            [(-1,-1),(0,-1),(0,0),(0,1)], [(-1,0),(-1,1),(0,0),(1,0)] ],
    "L": [ [(-1,1),(0,-1),(0,0),(0,1)], [(-1,0),(0,0),(1,0),(1,1)],
            [(0,-1),(0,0),(0,1),(1,-1)],  [(-1,-1),(-1,0),(0,0),(1,0)] ],
    "O": [ [(0,0),(0,1),(1,0),(1,1)] ],
    "S": [ [(0,0),(0,1),(1,-1),(1,0)],  [(-1,0),(0,0),(0,1),(1,1)] ],
    "T": [ [(0,-1),(0,0),(0,1),(1,0)],  [(-1,0),(0,0),(1,0),(0,1)],
            [(-1,0),(0,-1),(0,0),(0,1)], [(-1,0),(0,0),(1,0),(0,-1)] ],
    "Z": [ [(0,-1),(0,0),(1,0),(1,1)],  [(-1,1),(0,0),(0,1),(1,0)] ],
}
COLORS = {
    "I": curses.COLOR_CYAN,
    "J": curses.COLOR_BLUE,
    "L": curses.COLOR_YELLOW,   # looks orange‑ish on 8‑color sets
    "O": curses.COLOR_MAGENTA,
    "S": curses.COLOR_GREEN,
    "T": curses.COLOR_WHITE,
    "Z": curses.COLOR_RED,
}
BLOCK_CHAR = "█"                 # two‑column wide for smooth look

# ───────────────────────── Helper classes ─────────────────────────────────
class Piece:
    def __init__(self, kind: str):
        self.kind = kind
        self.rot  = 0
        self.row  = SPAWN_ROW
        self.col  = BOARD_W // 2

    # Return absolute coordinates of the blocks
    def cells(self):
        return [
            (self.row + dr, self.col + dc) for dr, dc in PIECES[self.kind][self.rot]
        ]

    def rotate(self, well):
        old = self.rot
        self.rot = (self.rot + 1) % len(PIECES[self.kind])
        if collision(self, well):
            self.rot = old  # revert if the rotated state collides


def new_piece() -> Piece:
    return Piece(random.choice(list(PIECES)))

# ─────────────────────── Collision / board logic ──────────────────────────

def collision(piece: Piece, well) -> bool:
    """True if piece overlaps settled blocks, walls or bottom.
    Cells above the board (row < 0) ignore occupancy checks but still obey
    horizontal boundaries.
    """
    for r, c in piece.cells():
        if c < 0 or c >= BOARD_W or r >= BOARD_H:
            return True
        if r >= 0 and well[r][c] is not None:
            return True
    return False


def lock_piece(piece: Piece, well):
    for r, c in piece.cells():
        if r >= 0:
            well[r][c] = piece.kind


def clear_lines(well) -> int:
    cleared = 0
    row = BOARD_H - 1
    while row >= 0:
        if all(well[row][c] is not None for c in range(BOARD_W)):
            cleared += 1
            del well[row]
            well.insert(0, [None] * BOARD_W)
        else:
            row -= 1
    return cleared

# ─────────────────────────── Main game ────────────────────────────────────

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    # Color pairs
    if curses.has_colors():
        curses.start_color()
        for idx, (k, clr) in enumerate(COLORS.items(), 1):
            curses.init_pair(idx, clr, clr)
        COLOR_IDX = {k: i+1 for i, k in enumerate(COLORS)}
    else:
        COLOR_IDX = {k: 0 for k in COLORS}

    def draw_cell(r: int, c: int, kind):
        y, x = top_offset + r, 1 + c*2
        if kind is None:
            stdscr.addstr(y, x, "  ")
        else:
            stdscr.addstr(y, x, BLOCK_CHAR*2, curses.color_pair(COLOR_IDX[kind]))

    # Build empty board
    well = [[None for _ in range(BOARD_W)] for _ in range(BOARD_H)]
    piece      = new_piece()
    next_piece = new_piece()

    score = lines = level = 0
    gravity_ms = GRAVITY_MS_START
    last_fall  = time.time()*1000

    # Static frame
    top_offset = 2  # rows reserved for score banner
    for r in range(BOARD_H):
        stdscr.addstr(top_offset + r, 0, "|")
        stdscr.addstr(top_offset + r, BOARD_W*2 + 1, "|")
    stdscr.addstr(top_offset + BOARD_H, 0, "+" + "-"*(BOARD_W*2) + "+")

    # ─────────────────── game loop ───────────────────
    while True:
        # ----- input -----
        key = stdscr.getch()
        soft = False
        if key != -1:
            if key in (ord('q'), ord('Q')):
                break
            elif key in (curses.KEY_LEFT, ord('a'), ord('A')):
                piece.col -= 1
                if collision(piece, well):
                    piece.col += 1
            elif key in (curses.KEY_RIGHT, ord('d'), ord('D')):
                piece.col += 1
                if collision(piece, well):
                    piece.col -= 1
            elif key in (curses.KEY_UP, ord('w'), ord('W')):
                piece.rotate(well)
            elif key in (curses.KEY_DOWN, ord('s'), ord('S')):
                soft = True
            elif key == ord(' '):  # hard‑drop
                while not collision(piece, well):
                    piece.row += 1
                piece.row -= 1

        # ----- gravity -----
        now = time.time()*1000
        interval = SOFT_DROP_MS if soft else gravity_ms
        if now - last_fall >= interval:
            piece.row += 1
            if collision(piece, well):
                piece.row -= 1
                lock_piece(piece, well)
                cleared = clear_lines(well)
                if cleared:
                    lines += cleared
                    score += (cleared * 100) * (level + 1)
                    level = lines // LVL_UP_EVERY
                    gravity_ms = max(MIN_GRAVITY_MS, GRAVITY_MS_START - level*50)
                piece = next_piece
                piece.row = SPAWN_ROW
                piece.col = BOARD_W // 2
                next_piece = new_piece()
                if collision(piece, well):  # spawn blocked
                    stdscr.nodelay(False)
                    stdscr.addstr(top_offset + BOARD_H//2, 2, " GAME OVER — press any key ")
                    stdscr.getch()
                    break
            last_fall = now

        # ----- draw well -----
        for r in range(BOARD_H):
            for c in range(BOARD_W):
                draw_cell(r, c, well[r][c])
        # active piece
        for r, c in piece.cells():
            if r >= 0:
                draw_cell(r, c, piece.kind)

        # banner
        banner = (f" Score: {score:<6}  Lines: {lines:<3}  Lv: {level:<2}"
                  f"  Next: {next_piece.kind}  Q: quit ")
        stdscr.addstr(0, 0, banner[:BOARD_W*2 + 2])

        stdscr.refresh()
        time.sleep(0.01)  # ease CPU


if __name__ == "__main__":
    curses.wrapper(main)
