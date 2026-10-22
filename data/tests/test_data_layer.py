import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("SUPABASE_URL", "http://x")

import tournament as T
from data import replay_store
from data.sync import Sync


class FakeSB:
    def __init__(self):
        self.tables = {}
        self.profiles = [{"id": "u-alice", "username": "Alice", "status": "new"},
                         {"id": "u-bob", "username": "bob", "status": "banned"}]

    def select_all(self, table, params=None):
        if table == "profiles":
            return self.profiles
        return []

    def upsert(self, table, rows, on_conflict, batch=500):
        self.tables.setdefault(table, []).extend(rows)
        return len(rows)


class ReplayStoreTests(unittest.TestCase):
    def test_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            games = [{"players": ["a", "b"], "result": 1, "moves": [[0, [0, 0, 1, 1]]]}]
            p, wrote = replay_store.save(1, 2, 3, 4, "alice", "bob", games, d)
            self.assertTrue(wrote)
            self.assertEqual(replay_store.load(1, 2, 3, 4, "alice", "bob", d), games)
            self.assertFalse(replay_store.save(1, 2, 3, 4, "alice", "bob", [], d)[1])
            self.assertIsNone(replay_store.read_gz_bytes(1, 2, 3, 5, "alice", "bob", d))

    def test_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            replay_store.replay_path(1, 1, 0, 1, "../etc", "bob")


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(":memory:")
        self.con.executescript(T.SCHEMA)
        c = self.con
        c.executemany("insert into users(name,token,entry,status) values(?,?,?,?)",
                      [("alice", "t1", 3.0, "active"), ("bob", "t2", 1.0, "active"), ("ghost", "t3", 0, "new")])
        c.executemany("insert into meta values(?,?)", [("phase", "round"), ("round", "1"), ("day", "2"), ("pending", "0")])
        c.executemany("insert into member values(?,?,?,?)", [(1, "alice", 0, 0), (1, "bob", 0, 1)])
        c.execute("insert into daily values(1,1,0,'alice',1,2,1,2)")
        c.execute("insert into daily values(1,1,0,'bob',-1,-2,2,2)")
        c.execute("insert into matches values(1,1,1,'alice','bob',2)")
        c.execute("insert into match_replays values(1,1,1,'alice','bob','[{\"result\":1}]')")
        c.commit()
        self.sb = FakeSB()
        self.sync = Sync(T, self.sb, self.con, replay_base=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_run(self):
        self.sync.run()
        t = self.sb.tables
        st = {r["username"]: r["status"] for r in t["profiles"]}
        self.assertEqual(st, {"Alice": "active", "bob": "banned"})        # banned giữ nguyên, ghost bị bỏ qua
        self.assertIn("ghost", self.sync.skipped)
        self.assertEqual(t["tournament_state"][0]["current_day"], 2)
        self.assertEqual(len(t["round_config"]), len(T.CFG["rounds"]))
        m = t["matches"][0]
        self.assertEqual((m["player_a"], m["player_b"], m["score_a"], m["has_replay"]), ("u-alice", "u-bob", 2, True))
        self.assertEqual(replay_store.load(1, 1, 0, 1, "alice", "bob", self.tmp.name), [{"result": 1}])
        states = {(r["rnd"], r["day"]): r["state"] for r in t["contest_days"]}
        self.assertEqual(states, {(1, 1): "graded", (1, 2): "open"})
        self.assertEqual(len(t["daily_results"]), 2)

    def test_idempotent_replays(self):
        self.assertEqual(self.sync.replays(), 1)
        self.assertEqual(self.sync.replays(), 0)


if __name__ == "__main__":
    unittest.main()
