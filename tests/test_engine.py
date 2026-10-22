import os
import unittest

import engine


RULE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rules")


class EngineReplayTests(unittest.TestCase):
    def test_play_can_capture_legal_moves_without_changing_its_result(self):
        def first_legal_move(state):
            board, player = engine._decode(state)
            return engine.legal_moves(board, player)[0]

        bots = [engine.FuncBot(first_legal_move), engine.FuncBot(first_legal_move)]
        recorded = []

        result = engine.play(bots, max_plies=1, moves=recorded)

        self.assertEqual(result, engine.play(bots, max_plies=1))
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0][0], 0)
        self.assertEqual(len(recorded[0][1]), 4)

    def test_entry_opponents_are_separate_from_full_strength_bots(self):
        self.assertIs(engine.make_bot("entry:0").fn, engine.entry_btc0)
        self.assertIs(engine.make_bot("entry:1").fn, engine.entry_btc1)
        self.assertIs(engine.make_bot("entry:2").fn, engine.entry_btc2)
        self.assertIs(engine.make_bot("btc:0").fn, engine.btc0)
        self.assertIs(engine.make_bot("btc:1").fn, engine.btc1)
        self.assertIs(engine.make_bot("btc:2").fn, engine.btc2)

    def test_progress_entry_opponent_selects_an_advancing_move_when_available(self):
        state = engine.encode(engine.initial(), 0, 0)
        board, player = engine._decode(state)

        move = engine.entry_btc1(state)

        self.assertLess(
            engine._dist(move[2], move[3], engine.GOAL[player]),
            engine._dist(move[0], move[1], engine.GOAL[player]),
        )
        self.assertIn(move, engine.legal_moves(board, player))

    def test_walls_block_entry(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule2.json"))
        board = {(2, 3): (0, 0)}

        self.assertNotIn((2, 3, 3, 3), engine.legal_moves(board, 0, rules))

    def test_teleport_is_optional_and_only_available_from_an_endpoint(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule4.json"))
        board = {(1, 2): (0, 0)}

        moves = engine.legal_moves(board, 0, rules)
        self.assertIn((1, 2, 7, 6), moves)

        entered = engine.apply({(0, 1): (0, 0)}, (0, 1, 1, 2), rules)
        self.assertIn((1, 2), entered)
        self.assertNotIn((7, 6), entered)

    def test_teleport_captures_only_when_piece_type_can_capture(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule4.json"))
        board = {(1, 2): (0, 0), (7, 6): (1, 2)}
        move = (1, 2, 7, 6)

        self.assertIn(move, engine.legal_moves(board, 0, rules))
        captured = engine.apply(board, move, rules)
        self.assertEqual(captured[(7, 6)], (0, 0))
        self.assertNotIn((1, 2), captured)

        board[(7, 6)] = (1, 1)
        self.assertNotIn(move, engine.legal_moves(board, 0, rules))

    def test_protected_piece_cannot_be_captured_from_outside(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule3.json"))
        board = {(1, 1): (0, 0), (2, 1): (1, 2)}

        self.assertNotIn((1, 1, 2, 1), engine.legal_moves(board, 0, rules))

    def test_piece_inside_protection_zone_can_capture_outside_piece(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule3.json"))
        board = {(2, 1): (0, 0), (3, 2): (1, 2)}

        self.assertIn((2, 1, 3, 2), engine.legal_moves(board, 0, rules))

    def test_pieces_inside_protection_zone_cannot_capture_each_other(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule3.json"))
        board = {(2, 1): (0, 0), (3, 1): (1, 2)}

        self.assertNotIn((2, 1, 3, 1), engine.legal_moves(board, 0, rules))

    def test_rules_progress_cumulatively_by_round(self):
        round_rules = [
            engine.load_rules(os.path.join(RULE_DIR, f"rule{number}.json"))["board"]
            for number in range(1, 6)
        ]

        self.assertFalse(round_rules[0]["walls"])
        self.assertFalse(round_rules[0]["protection_zones"])
        self.assertFalse(round_rules[0]["teleporters"])
        self.assertFalse(round_rules[0]["piece_changers"])
        self.assertTrue(round_rules[1]["walls"])
        self.assertFalse(round_rules[1]["protection_zones"])
        self.assertEqual(len(round_rules[2]["protection_zones"]), 4)
        self.assertFalse(round_rules[2]["teleporters"])
        self.assertTrue(round_rules[3]["teleporters"])
        self.assertFalse(round_rules[3]["piece_changers"])
        self.assertTrue(round_rules[4]["piece_changers"])

    def test_piece_changer_applies_when_entering_and_again_on_reentry(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule5.json"))
        board = {(3, 4): (0, 0)}

        board = engine.apply(board, (3, 4, 4, 4), rules)
        self.assertEqual(board[(4, 4)], (0, 2))
        board = engine.apply(board, (4, 4, 5, 4), rules)
        board = engine.apply(board, (5, 4, 4, 4), rules)
        self.assertEqual(board[(4, 4)], (0, 1))

    def test_rule5_has_no_overlapping_special_cells_and_one_center_changer(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule5.json"))
        board_rules = rules["board"]
        special_cells = [tuple(cell) for cell in board_rules["walls"]]
        special_cells.extend(
            tuple(end)
            for teleporter in board_rules["teleporters"]
            for end in teleporter["ends"]
        )
        special_cells.extend(
            tuple(cell)
            for zone in board_rules["protection_zones"]
            for cell in zone
        )
        special_cells.extend(
            tuple(changer["position"])
            for changer in board_rules["piece_changers"]
        )

        self.assertEqual(len(special_cells), len(set(special_cells)))
        self.assertEqual(
            [changer["position"] for changer in board_rules["piece_changers"]],
            [[4, 4]],
        )

    def test_overlapping_special_cells_are_rejected(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule4.json"))
        rules["board"]["walls"].append([1, 2])

        with self.assertRaisesRegex(ValueError, "bị khai báo trùng"):
            engine._normalize_rules(rules)

    def test_protection_zones_must_be_horizontal_and_symmetric(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule3.json"))
        rules["board"]["protection_zones"][0] = [[2, 1], [2, 2]]

        with self.assertRaisesRegex(ValueError, "chiều ngang"):
            engine._normalize_rules(rules)

    def test_encoded_bot_state_contains_active_rules(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule2.json"))

        state = engine.encode(engine.initial(), 0, 0, rules)

        self.assertEqual(state["rules"], rules)

    def test_play_sends_rules_to_bots_and_accepts_rule_aware_moves(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule3.json"))
        received_rules = []

        def first_legal_move(state):
            received_rules.append(state["rules"])
            board, player = engine._decode(state)
            return engine.legal_moves(board, player, state["rules"])[0]

        bots = [engine.FuncBot(first_legal_move), engine.FuncBot(first_legal_move)]

        result = engine.play(bots, max_plies=2, rules=rules)

        self.assertEqual(result, 0)
        self.assertEqual(received_rules, [rules, rules])

    def test_builtin_bots_choose_legal_moves_with_custom_rules(self):
        rules = engine.load_rules(os.path.join(RULE_DIR, "rule5.json"))
        state = engine.encode(engine.initial(), 0, 0, rules)
        board, player = engine._decode(state)
        legal = engine.legal_moves(board, player, rules)

        for spec in ("btc:0", "btc:1", "btc:2", "entry:0", "entry:1", "entry:2"):
            with self.subTest(spec=spec):
                self.assertIn(engine.make_bot(spec).fn(state), legal)

    def test_match_points_include_base_result_and_per_game_bonuses(self):
        def decisive_game(a_player):
            b_player = 1 - a_player
            players = ["a", "b"] if a_player == 0 else ["b", "a"]
            row = 0 if a_player == 0 else 8
            target_row = 8 if a_player == 0 else 0
            source = (0, row)
            moves = []
            for index in range(5):
                destination = (index, target_row)
                moves.append((a_player, (*source, *destination)))
                source = destination
                if index < 4:
                    opponent_x = 8 - index
                    moves.append((
                        b_player,
                        (opponent_x, target_row, opponent_x, target_row + (1 if target_row == 0 else -1)),
                    ))
            return {"players": players, "result": 1, "moves": moves}

        games = [decisive_game(0), decisive_game(1)]

        self.assertEqual(engine.match_game_bonus(games), 20)
        self.assertEqual(engine.match_score_delta(2, games), 50)
        self.assertEqual(engine.match_score_delta(-2, []), -30)
        self.assertEqual(engine.match_score_delta(0, []), 0)

    def test_game_bonus_stacks_and_draws_do_not_receive_bonus(self):
        self.assertEqual(engine._game_bonus(1, 5, 40), 10)
        self.assertEqual(engine._game_bonus(-1, 5, 40), -10)
        self.assertEqual(engine._game_bonus(1, 4, 41), 0)
        self.assertEqual(engine._game_bonus(0, 9, 1), 0)


if __name__ == "__main__":
    unittest.main()
