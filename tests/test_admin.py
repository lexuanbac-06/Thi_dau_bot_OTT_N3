import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["FLASK_SECRET_KEY"] = "test-flask-secret"

import server


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        server.T.DB = str(root / "ott.db")
        server.T.BOT_DIR = str(root / "bots")
        server.T.SNAP = str(root / "snaps")
        server.T.init()
        with server._admin_job_lock:
            server._admin_job = None
        self.client = server.app.test_client()
        page = self.client.get("/admin")
        self.csrf = re.search(
            rb'name="csrf_token" value="([^"]+)"', page.data
        ).group(1).decode()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self):
        response = self.client.post(
            "/admin",
            data={"csrf_token": self.csrf, "password": "test-admin-password"},
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
        for _ in range(100):
            job = self.client.get("/admin/api/job").json
            if job["state"] != "running":
                return job
            time.sleep(0.01)
        self.fail("Admin action did not finish")

    def test_admin_routes_require_login_and_csrf(self):
        self.assertEqual(self.client.get("/admin/api/overview").status_code, 401)
        self.assertEqual(
            self.client.post("/admin", data={
                "csrf_token": self.csrf,
                "password": "incorrect",
            }).status_code,
            401,
        )
        self.login()
        self.assertEqual(self.client.get("/admin/api/overview").status_code, 200)
        self.assertEqual(
            self.client.post("/admin/api/submissions", json={"accepting": False}).status_code,
            403,
        )

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
