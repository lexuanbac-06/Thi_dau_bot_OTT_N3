import json
import os
import re
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["FLASK_SECRET_KEY"] = "test-flask-secret"
os.environ["OTT_SUPABASE_SYNC"] = "0"

import server


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        server.T.DB = str(root / "ott.db")
        server.T.BOT_DIR = str(root / "bots")
        server.T.SNAP = str(root / "snaps")
        server.T.LIVE_BOARD_SNAPSHOT = str(root / "static" / "live-board.json")
        server.T.init()
        server.T.publish_live_tournament_snapshot()
        with server._admin_job_lock:
            server._admin_job = None
        self.client = server.app.test_client()

        self.patch_login = patch.object(
            server.A, "login",
            side_effect=lambda u, p, ip=None, ua=None: (
                (_ for _ in ()).throw(PermissionError("Sai tên hoặc mật khẩu"))
                if p == "incorrect" else {
                    "access_token": "mock-token",
                    "refresh_token": "mock-rt",
                    "expires_in": 3600,
                    "user": {"id": "mock-id", "username": u or "admin_user", "role": "admin", "status": "active"}
                }
            )
        )
        self.patch_login.start()

        self.patch_verify = patch.object(
            server.A, "verify_token",
            side_effect=lambda tok: {
                "id": "mock-id", "username": "admin_user", "role": "admin", "status": "active"
            }
        )
        self.patch_verify.start()

        page = self.client.get("/login")
        self.assertEqual(page.status_code, 200)
        with self.client.session_transaction() as session:
            self.csrf = session["csrf_token"]

    def tearDown(self):
        self.patch_login.stop()
        self.patch_verify.stop()
        self.temp_dir.cleanup()

    def login(self):
        response = self.client.post(
            "/login",
            data={"csrf_token": self.csrf, "username": "admin_user", "password": "correct_password"},
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.csrf = session["csrf_token"]
        dashboard = self.client.get("/admin")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Ch\xe1\xba\xa5m \xc4\x91\xe1\xba\xa7u v\xc3\xa0o v\xc3\xa0 chia b\xe1\xba\xa3ng", dashboard.data)

    def post_headers(self):
        return {"X-CSRF-Token": self.csrf}

    def wait_for_job(self):
        for _ in range(300):
            job = self.client.get("/admin/api/job").json
            if job["state"] != "running":
                return job
            time.sleep(0.01)
        self.fail("Admin action did not finish")

    def test_admin_routes_require_login_and_csrf(self):
        self.assertEqual(self.client.get("/admin/api/overview").status_code, 401)
        self.assertEqual(
            self.client.post("/login", data={
                "csrf_token": self.csrf,
                "username": "admin_user",
                "password": "incorrect",
            }).status_code,
            401,
        )
        self.login()
        overview = self.client.get("/admin/api/overview")
        self.assertEqual(overview.status_code, 200)
        self.assertNotIn("google_sheets_configured", overview.json)
        self.assertEqual(
            self.client.post("/admin/api/submissions", json={"accepting": False}).status_code,
            403,
        )

    def test_local_live_scores_are_upserted_and_published_publicly(self):
        self.login()
        server.T.register("entrant")
        server.T.register("challenger")
        server.T.register("third")
        response = self.client.post(
            "/admin/api/live-scores",
            json={
                "event": "Vòng 1",
                "scores": [{"name": "entrant", "score": 7.5}],
            },
            headers=self.post_headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json, {"ok": True, "saved": 1})

        response = self.client.post(
            "/admin/api/live-scores",
            json={
                "event": "Vòng 1",
                "scores": [{"name": "entrant", "score": 9}],
            },
            headers=self.post_headers(),
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            "/admin/api/live-scores",
            json={
                "event": "Vòng 2",
                "scores": [
                    {"name": "entrant", "score": 1},
                    {"name": "challenger", "score": 10},
                    {"name": "third", "score": 2},
                ],
            },
            headers=self.post_headers(),
        )
        self.assertEqual(response.status_code, 201)

        rows = self.client.get("/live-leaderboard").json
        self.assertEqual(
            [(row["rank"], row["name"], row["total"]) for row in rows],
            [(1, "challenger", 10), (1, "entrant", 10), (3, "third", 2)],
        )

    def test_live_score_validation_rejects_unknown_players_and_bool_scores(self):
        self.login()
        server.T.register("entrant")
        response = self.client.post(
            "/admin/api/live-scores",
            json={"event": "Vòng 1", "scores": [{"name": "unknown", "score": 1}]},
            headers=self.post_headers(),
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/admin/api/live-scores",
            json={"event": "Vòng 1", "scores": [{"name": "entrant", "score": True}]},
            headers=self.post_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/live-leaderboard").json, [])

    def test_static_live_snapshot_hides_partial_tables_and_keeps_personal_progress(self):
        server.T.register("entrant")
        server.T.register("challenger")
        server.T.register("third")
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,?,?,?)",
            ("entrant", 1, 1),
        )
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,?,?,?)",
            ("challenger", 1, 2),
        )
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,?,?,?)",
            ("third", 2, 1),
        )
        server.T.put("live_scoring", '{"state":"running","round":1,"day":1,"completed_rounds":1,"total_rounds":3,"completed_matches":1,"total_matches":3}')

        server.T.put(
            "live_scoring_queue",
            json.dumps([
                {"group": 2, "a": "another_a", "b": "another_b"},
                {"group": 1, "a": "entrant", "b": "challenger"},
            ]),
        )
        server.T.put("live_scoring_completed", "[0]")
        server.T.publish_live_tournament_snapshot()
        with patch.object(
            server.T,
            "live_tournament_board",
            side_effect=AssertionError("Static file reads must not query SQLite"),
        ):
            response = self.client.get("/live-board.json")

        self.assertEqual(response.status_code, 200)
        self.assertIn("s-maxage=20", response.headers["Cache-Control"])
        self.assertEqual(response.json["completed_rounds"], 1)
        self.assertEqual(response.json["groups"], [])
        self.assertEqual(response.json["players"]["entrant"]["group"], 1)
        self.assertEqual(response.json["players"]["entrant"]["matches_played"], 0)
        self.assertFalse(response.json["players"]["entrant"]["group_complete"])
        self.assertEqual(response.json["players"]["entrant"]["queue_ahead"], 0)
        response.close()

    def test_live_board_reveals_only_completed_personal_group(self):
        server.T.register("entrant")
        server.T.register("challenger")
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,'entrant',1,1)"
        )
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,'challenger',1,2)"
        )
        for match_round in range(1, server.T.MATCHES + 1):
            server.T.q(
                "insert into matches values(1,1,?,'entrant','challenger',1)",
                (match_round,),
            )
        server.T.put(
            "live_scoring",
            json.dumps({
                "state": "running",
                "round": 1,
                "day": 1,
                "completed_rounds": 2,
                "total_rounds": server.T.MATCHES,
                "completed_matches": server.T.MATCHES,
                "total_matches": server.T.MATCHES,
            }),
        )
        server.T.publish_live_tournament_snapshot()

        response = self.client.get("/live-board.json")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["players"]["entrant"]["group_complete"])
        self.assertEqual([group["group"] for group in response.json["groups"]], [1])
        self.assertEqual(
            [row["name"] for row in response.json["groups"][0]["entrants"]],
            ["entrant", "challenger"],
        )
        first_group = response.json["groups"][0]["entrants"]
        self.assertEqual(
            [(row["rank"], row["name"], row["pts"], row["gs"], row["matches_played"])
             for row in first_group],
            [
                (1, "entrant", server.T.MATCHES, server.T.MATCHES, server.T.MATCHES),
                (2, "challenger", -server.T.MATCHES, -server.T.MATCHES, server.T.MATCHES),
            ],
        )
        response.close()

    def test_grade_day_persists_live_progress_after_each_round(self):
        server.T.put("round", 1)
        server.T.put("pending", 1)
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,'entrant',1,1)"
        )
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,'challenger',1,2)"
        )
        class InlinePool:
            def __init__(self, workers):
                self.workers = workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def map(self, function, args, chunksize):
                return [function(arg) for arg in args]

            def imap_unordered(self, function, args, chunksize):
                return (function(arg) for arg in args)

        with patch.object(server.T, "Pool", InlinePool):
            with redirect_stdout(StringIO()):
                server.T.grade_day()

        snapshot = json.loads(Path(server.T.LIVE_BOARD_SNAPSHOT).read_text(encoding="utf-8"))
        self.assertEqual(snapshot["completed_rounds"], server.T.MATCHES)
        self.assertEqual(snapshot["state"], "complete")
        self.assertEqual(snapshot["completed_matches"], server.T.MATCHES)
        self.assertEqual(len(snapshot["groups"]), 1)
        self.assertEqual(
            [row["matches_played"] for row in snapshot["groups"][0]["entrants"]],
            [server.T.MATCHES, server.T.MATCHES],
        )

    def test_sheet_sync_api_is_removed(self):
        routes = {rule.rule for rule in server.app.url_map.iter_rules()}
        self.assertNotIn("/live-leaderboard-source", routes)
        self.assertNotIn("/admin/api/live-tournament-board/sync", routes)
        self.assertNotIn("/admin/api/live-scores/sync", routes)
        self.assertNotIn("/api/live-tournament-board", routes)

    def test_admin_login_sets_a_persistent_session_cookie(self):
        response = self.client.post(
            "/login",
            data={"csrf_token": self.csrf, "username": "admin_user", "password": "correct_password"},
        )

        self.assertEqual(response.status_code, 302)
        cookie = response.headers["Set-Cookie"]
        self.assertIn("Expires=", cookie)
        self.assertNotIn("correct_password", cookie)
        with self.client.session_transaction() as session:
            self.assertTrue(session.permanent)
        self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_submission_switch_is_enforced_and_admin_list_hides_tokens(self):
        self.login()
        response = self.client.post(
            "/admin/api/submissions",
            json={"accepting": False},
            headers=self.post_headers(),
        )
        self.assertEqual(response.status_code, 200)
        server.T.register("entrant")
        with self.assertRaisesRegex(ValueError, "tạm đóng"):
            server.T.submit("entrant", b"print(1)")

        self.client.post(
            "/admin/api/submissions",
            json={"accepting": True},
            headers=self.post_headers(),
        )
        server.T.submit("entrant", b"print(1)")
        entrant = self.client.get("/admin/api/overview").json["entrants"][0]
        self.assertEqual(entrant["name"], "entrant")
        self.assertTrue(entrant["has_bot"])
        self.assertNotIn("token", entrant)

    def test_entry_elimination_explains_why_submission_is_rejected(self):
        name = "entrant"
        server.T.register(name)
        server.T.put("phase", "round")
        server.T.put("round", 1)
        server.T.q("update users set status='out' where name=?", (name,))

        with self.assertRaisesRegex(ValueError, "đủ điều kiện qua vòng đầu vào"):
            server.T.submit(name, b"print(1)")

    def test_later_elimination_is_distinguished_from_entry_elimination(self):
        name = "entrant"
        server.T.register(name)
        server.T.put("phase", "round")
        server.T.put("round", 2)
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,?,0,0)",
            (name,),
        )
        server.T.q("update users set status='out' where name=?", (name,))

        with self.assertRaisesRegex(ValueError, "bị loại khỏi cuộc thi ở vòng trước"):
            server.T.submit(name, b"print(1)")

    def test_replays_only_show_matches_from_the_entrant_group(self):
        server.T.register("entrant")
        server.T.register("opponent")
        server.T.register("other")
        server.T.qm(
            "insert into member(rnd,name,grp,seed) values(1,?,0,0)",
            [("entrant",), ("opponent",)],
        )
        server.T.qm(
            "insert into member(rnd,name,grp,seed) values(1,?,1,0)",
            [("other",)],
        )
        server.T.q(
            "insert into matches(rnd,day,rd,a,b,s) values(1,1,1,'entrant','opponent',2)"
        )
        server.T.qm(
            "insert into daily values(1,1,0,?,0,0,?,2)",
            [("entrant", 1), ("opponent", 2)],
        )
        server.T.q(
            "insert into match_replays(rnd,day,rd,a,b,games) values(1,1,1,'entrant','opponent',?)",
            ('[{"players":["a","b"],"result":1,"moves":[[0,[0,0,1,1]]]}]',),
        )
        server.T.q(
            "insert into matches(rnd,day,rd,a,b,s) values(1,1,1,'other','other2',0)"
        )
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,'other2',1,1)"
        )

        result = server.T.replays("entrant")

        self.assertEqual(result["available"], [{"round": 1, "day": 1}])
        self.assertEqual(len(result["matches"]), 1)
        self.assertEqual(result["matches"][0]["games"][0]["moves"][0][0], 0)

    def test_entry_action_runs_and_reports_completion(self):
        self.login()

        def fake_entry_close():
            server.T.put("phase", "round")
            server.T.put("round", 1)
            server.T.put("day", 1)

        with patch.object(server.T, "entry_close", fake_entry_close):
            response = self.client.post(
                "/admin/api/actions/entry-close",
                headers=self.post_headers(),
            )
            self.assertEqual(response.status_code, 202)
            job = self.wait_for_job()
        self.assertEqual(job["state"], "complete")
        self.assertEqual(job["action"], "Chấm đầu vào và chia bảng")

    def test_final_round_persists_and_announces_champion(self):
        server.T.register("champion")
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,'champion',0,0)"
        )
        server.T.q(
            "insert into daily values(1,?,0,'champion',3,4,1,1)",
            (server.T.DAYS,),
        )

        with (
            patch.dict(server.T.CFG, {"rounds": [{"groups": 1, "top": 1, "wildcard": 0}]}),
            redirect_stdout(StringIO()),
        ):
            server.T.advance(1)

        self.assertEqual(server.T.get("phase"), "done")
        self.assertEqual(server.T.get("champion"), "champion")
        self.assertEqual(server.T.admin_overview()["champion"], "champion")
        response = self.client.get("/champion")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"champion": "champion"})

    def test_tournament_reset_clears_entries_results_and_bot_files(self):
        self.login()
        server.T.register("entrant")
        server.T.submit("entrant", b"print(1)")
        server.T.put("phase", "round")
        server.T.put("round", 1)
        server.T.put("day", 2)
        server.T.put("pending", 1)
        server.T.q(
            "insert into member(rnd,name,grp,seed) values(1,'entrant',0,0)"
        )
        server.T.q(
            "insert into daily values(1,1,0,'entrant',1,1,1,1)"
        )
        snapshot = Path(server.T.SNAP) / "r1" / "d1"
        snapshot.mkdir(parents=True)
        (snapshot / "entrant.py").write_text("print(1)", encoding="utf-8")

        response = self.client.post(
            "/admin/api/actions/reset",
            headers=self.post_headers(),
        )
        self.assertEqual(response.status_code, 202)
        job = self.wait_for_job()

        self.assertEqual(job["state"], "complete")
        self.assertEqual(job["action"], "Reset toàn bộ cuộc thi")
        overview = server.T.admin_overview()
        self.assertEqual(overview["phase"], "entry")
        self.assertIsNone(overview["round"])
        self.assertIsNone(overview["day"])
        self.assertIsNone(overview["pending"])
        self.assertTrue(overview["accepting_submissions"])
        self.assertEqual(overview["entrants"], [])
        self.assertEqual(list(Path(server.T.BOT_DIR).iterdir()), [])
        self.assertEqual(list(Path(server.T.SNAP).iterdir()), [])

    def test_day_close_and_grade_actions_follow_tournament_state(self):
        self.login()
        server.T.put("phase", "round")
        server.T.put("round", 1)
        server.T.put("day", 1)
        server.T.put("pending", 0)

        def fake_close_day():
            server.T.put("pending", 1)
            server.T.put("day", 2)

        with patch.object(server.T, "close_day", fake_close_day):
            response = self.client.post(
                "/admin/api/actions/close-day",
                headers=self.post_headers(),
            )
            self.assertEqual(response.status_code, 202)
            self.assertEqual(self.wait_for_job()["state"], "complete")
        self.assertTrue(server.T.admin_overview()["accepting_submissions"])
        self.assertEqual(server.T.admin_overview()["pending"], 1)

        def fake_grade_day():
            server.T.put("pending", 0)
            server.T.put("phase", "done")

        with patch.object(server.T, "grade_day", fake_grade_day):
            response = self.client.post(
                "/admin/api/actions/grade-day",
                headers=self.post_headers(),
            )
            self.assertEqual(response.status_code, 202)
            job = self.wait_for_job()
        self.assertEqual(job["state"], "complete")
        self.assertEqual(server.T.get("phase"), "done")


if __name__ == "__main__":
    unittest.main()
