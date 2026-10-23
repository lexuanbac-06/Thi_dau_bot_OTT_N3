import csv
import io
from io import BytesIO

import pytest

from finals import auth, db


def initialize_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finalists.db"))
    monkeypatch.setattr(db, "_initialized", False)
    db.init()
    db.migrate()


def finalist_csv(username="finalist_1"):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "user_id",
            "username",
            "email",
            "advance_route",
            "final_rank",
            "avg_rank_pct",
        ],
    )
    writer.writeheader()
    writer.writerow({
        "user_id": "f4d5eaf1-b9fa-40b3-a035-d3c5f46550d2",
        "username": username,
        "email": "finalist@example.com",
        "advance_route": "top",
        "final_rank": "1",
        "avg_rank_pct": "95.5",
    })
    return output.getvalue()


def test_import_finalists_issues_local_password_and_allows_login(tmp_path, monkeypatch):
    initialize_db(tmp_path, monkeypatch)

    credentials = auth.import_finalists_csv(finalist_csv())

    assert len(credentials) == 1
    assert credentials[0]["username"] == "finalist_1"
    assert len(auth.login("finalist_1", credentials[0]["password"])) == 64
    row = db.fetchone(
        "SELECT email, advance_route, final_rank, password FROM contestants WHERE username=?",
        ("finalist_1",),
    )
    assert row["email"] == "finalist@example.com"
    assert row["advance_route"] == "top"
    assert row["final_rank"] == 1
    assert row["password"] != credentials[0]["password"]


def test_importing_roster_again_rotates_local_password(tmp_path, monkeypatch):
    initialize_db(tmp_path, monkeypatch)

    first = auth.import_finalists_csv(finalist_csv())[0]
    second = auth.import_finalists_csv(finalist_csv())[0]

    with pytest.raises(PermissionError):
        auth.login("finalist_1", first["password"])
    assert len(auth.login("finalist_1", second["password"])) == 64


def test_import_rejects_conflict_atomically(tmp_path, monkeypatch):
    initialize_db(tmp_path, monkeypatch)
    auth.register_contestant("already_here", "local-pass", "Local User")
    content = finalist_csv("already_here")

    with pytest.raises(ValueError, match="xung đột"):
        auth.import_finalists_csv(content)

    assert db.fetchone(
        "SELECT username FROM contestants WHERE username=?",
        ("already_here",),
    )["username"] == "already_here"


def test_import_rejects_unicode_username(tmp_path, monkeypatch):
    initialize_db(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="Username không hợp lệ"):
        auth.import_finalists_csv(finalist_csv("thí_sinh"))


def test_import_rejects_duplicate_rows(tmp_path, monkeypatch):
    initialize_db(tmp_path, monkeypatch)
    content = finalist_csv() + finalist_csv().splitlines()[1] + "\n"

    with pytest.raises(ValueError, match="bị trùng"):
        auth.import_finalists_csv(content)
    assert auth.list_contestants() == []


def test_admin_import_endpoint_returns_downloadable_local_credentials(tmp_path, monkeypatch):
    initialize_db(tmp_path, monkeypatch)
    from finals import app as finals_app

    monkeypatch.setattr(finals_app, "ADMIN_SECRET", "admin-secret")
    client = finals_app.app.test_client()
    response = client.post(
        "/finals/admin/import-finalists",
        headers={"X-Admin-Secret": "admin-secret"},
        data={"file": (BytesIO(finalist_csv().encode("utf-8")), "finalists.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    payload = response.get_json()
    assert payload["imported"] == 1
    assert "offline_password" in payload["credentials_csv"]
    assert "finalist_1" in payload["credentials_csv"]
    issued = next(csv.DictReader(io.StringIO(payload["credentials_csv"])))
    assert len(auth.login("finalist_1", issued["offline_password"])) == 64
