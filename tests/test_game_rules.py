import json
from pathlib import Path
import subprocess
import sys
import unittest

import engine
from servers.scoring import game_rules, judge0_runner


ROOT = Path(__file__).resolve().parents[1]
RULE_DIR = ROOT / "rules"
SAMPLE_BOT = ROOT / "frontend" / "public" / "sample_bot.py"


def load_rule(number):
    with (RULE_DIR / f"rule{number}.json").open(encoding="utf-8") as rule_file:
        return json.load(rule_file)


class TournamentGameRulesTests(unittest.TestCase):
    def test_all_rule_presets_are_normalized_without_changing_their_data(self):
        for number in range(1, 6):
            with self.subTest(rule=number):
                data = load_rule(number)
                self.assertEqual(game_rules.normalize_rules(data), data)
                self.assertEqual(
                    game_rules.legal_moves(game_rules.initial(), 0, data),
                    engine.legal_moves(engine.initial(), 0, data),
                )

    def test_walls_block_moves(self):
        rules = game_rules.normalize_rules(load_rule(2))
        board = {(2, 3): (0, 0)}

        self.assertNotIn((2, 3, 3, 3), game_rules.legal_moves(board, 0, rules))

    def test_protected_piece_cannot_be_captured_from_outside(self):
        rules = game_rules.normalize_rules(load_rule(3))
        board = {(1, 1): (0, 0), (2, 1): (1, 2)}

        self.assertNotIn((1, 1, 2, 1), game_rules.legal_moves(board, 0, rules))

    def test_teleport_is_optional_and_can_capture_only_a_legal_target(self):
        rules = game_rules.normalize_rules(load_rule(4))
        board = {(1, 2): (0, 0), (7, 6): (1, 2)}
        teleport_move = (1, 2, 7, 6)

        self.assertIn(teleport_move, game_rules.legal_moves(board, 0, rules))
        self.assertEqual(
            game_rules.apply_move(board, teleport_move, rules)[(7, 6)],
            (0, 0),
        )
        board[(7, 6)] = (1, 1)
        self.assertNotIn(teleport_move, game_rules.legal_moves(board, 0, rules))

    def test_piece_changer_applies_on_each_entry(self):
        rules = game_rules.normalize_rules(load_rule(5))
        board = {(3, 4): (0, 0)}

        board = game_rules.apply_move(board, (3, 4, 4, 4), rules)
        self.assertEqual(board[(4, 4)], (0, 2))
        board = game_rules.apply_move(board, (4, 4, 5, 4), rules)
        board = game_rules.apply_move(board, (5, 4, 4, 4), rules)
        self.assertEqual(board[(4, 4)], (0, 1))

    def test_generated_judge0_program_contains_validated_rules_and_compiles(self):
        source = judge0_runner._runner_source(
            b"def choose_move(state): return (0, 0, 0, 1)",
            b"def choose_move(state): return (0, 0, 0, 1)",
            load_rule(5),
        )

        compile(source, "<judge0-runner>", "exec")
        self.assertIn('"rules": rules', source)
        self.assertIn('"rules": RULES', source)
        self.assertIn("piece_changers", source)

    def test_downloadable_sample_bot_returns_a_move_legal_under_selected_rules(self):
        rules = game_rules.normalize_rules(load_rule(5))
        state = game_rules.encode_state(game_rules.initial(), 0, 0, rules)
        result = subprocess.run(
            [sys.executable, str(SAMPLE_BOT)],
            input=json.dumps(state),
            text=True,
            capture_output=True,
            check=True,
            timeout=3,
        )
        move = tuple(map(int, result.stdout.split()))

        self.assertIn(move, game_rules.legal_moves(game_rules.initial(), 0, rules))

    def test_invalid_overlapping_special_cells_are_rejected(self):
        rules = load_rule(4)
        rules["board"]["walls"].append([1, 2])

        with self.assertRaisesRegex(ValueError, "Overlapping special cell"):
            game_rules.normalize_rules(rules)


if __name__ == "__main__":
    unittest.main()
