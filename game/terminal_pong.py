import curses
import random
import time

# --- Tweakable constants ----------------------------------------------------
PADDLE_STEP = 2   # rows the paddle moves per key‑press
FRAME_MS    = 50  # refresh rate in milliseconds  (≈20 FPS)
BALL_SLEEP  = 0.01  # extra sleep per frame to keep ball speed like the original


def main(stdscr):
    """Terminal Pong without flickering borders"""
    curses.curs_set(0)          # Hide the cursor
    stdscr.nodelay(True)        # Non‑blocking keyboard reads
    stdscr.timeout(FRAME_MS)    # Target FPS (affects ball speed)

    # Screen size
    sh, sw = stdscr.getmaxyx()

    # Draw static play‑field border once
    stdscr.border()

    # Paddle initialisation
    paddle_height = 4
    paddle_y = sh // 2 - paddle_height // 2
    paddle_x = 2  # Fixed column (left side)

    # Ball initialisation
    ball_y = sh // 2
    ball_x = sw // 2
    dir_y = random.choice([-1, 1])  # Up or down
    dir_x = -1                       # Always start moving left

    # Keep previous positions to erase moving objects cleanly
    prev_ball = (ball_y, ball_x)
    prev_paddle_y = paddle_y

    score = 0

    # ---------------------------- Game loop ---------------------------------
    while True:
        # ------------------------- Input ------------------------------------
        key = stdscr.getch()
        if key == ord("q"):
            break
        elif key in (ord("w"), curses.KEY_UP):
            paddle_y = max(1, paddle_y - PADDLE_STEP)
        elif key in (ord("s"), curses.KEY_DOWN):
            paddle_y = min(sh - paddle_height - 1, paddle_y + PADDLE_STEP)

        # ------------------------ Physics -----------------------------------
        ball_y += dir_y
        ball_x += dir_x

        # Bounce off top/bottom walls
        if ball_y <= 1 or ball_y >= sh - 2:
            dir_y *= -1

        # Bounce off paddle
        if (
            ball_x == paddle_x + 1
            and paddle_y <= ball_y <= paddle_y + paddle_height - 1
        ):
            dir_x *= -1
            score += 1

        # Missed paddle — game over
        if ball_x <= 0:
            stdscr.nodelay(False)
            stdscr.addstr(sh // 2, sw // 2 - 5, "Game Over!")
            stdscr.addstr(
                sh // 2 + 1,
                sw // 2 - 11,
                f"Final score: {score}. Press any key.",
            )
            stdscr.getch()
            break

        # Bounce off right wall (simple AI)
        if ball_x >= sw - 2:
            dir_x *= -1

        # ------------------------ Rendering ---------------------------------
        # 1. Erase previous ball
        stdscr.addch(prev_ball[0], prev_ball[1], " ")

        # 2. Erase previous paddle if it moved
        if prev_paddle_y != paddle_y:
            for i in range(paddle_height):
                stdscr.addch(prev_paddle_y + i, paddle_x, " ")

        # 3. Draw new paddle
        for i in range(paddle_height):
            stdscr.addch(paddle_y + i, paddle_x, "|")

        # 4. Draw new ball
        stdscr.addch(ball_y, ball_x, "O")

        # 5. HUD (overwrite only that area)
        stdscr.addstr(
            0,
            2,
            f" Score: {score}  (w/s or ↑/↓ move {PADDLE_STEP}px, q quit) ",
        )

        stdscr.refresh()

        # 6. Prepare for next iteration
        prev_ball = (ball_y, ball_x)
        prev_paddle_y = paddle_y

        time.sleep(BALL_SLEEP)


if __name__ == "__main__":
    curses.wrapper(main)
