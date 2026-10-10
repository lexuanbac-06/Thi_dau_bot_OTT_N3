import unittest

import engine


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


if __name__ == "__main__":
    unittest.main()
