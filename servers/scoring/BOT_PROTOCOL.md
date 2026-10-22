# OTT bot execution contract

Contestants' Python file must define a function named `choose_move(state)` or
`choose_best_move(state)`. The scoring module launches the file in a Judge0
sandbox and keeps its process alive for one game. The driver sends one JSON
state per turn over stdin; the function returns `(x, y, next_x, next_y)`.

`state` contains:

```json
{
  "me": 0,
  "ply": 0,
  "goal": [8, 8],
  "pieces": [[0, 0, 0, 0], [1, 0, 0, 1]]
}
```

Each piece is `[x, y, owner, kind]`, with coordinates from 0 to 8,
`owner` 0 or 1, and `kind` 0 (Hammer), 1 (Paper), or 2 (Scissors). A bot may
use module-level state to remember information during a game. The process is
restarted between the two BO2 games.

The module expects a four-coordinate return value. Missing functions, crashes,
timeouts, malformed returns, and illegal moves lose that game. The per-move
limits are 3 seconds for the first two plies and 1 second afterward. Judge0
also applies whole-submission CPU, wall-clock, memory, and process limits.
The frontend displays the fixed default Python 3/PyPy 3 runtime reported by the
local Judge0 instance. The module selects its language ID from
`OTT_JUDGE0_PYTHON_ID` (default `71`); the contestant cannot change it. The bot
file must follow this Python function contract; C++/Java are not compatible
with this runner yet.

Do not place a stdin loop at module top level. For local manual play, put it
under `if __name__ == "__main__":` so the scoring driver can import the
function without consuming its protocol input. See `sample_bots/sample_bot.py`
for a complete example.
