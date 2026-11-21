"""Tests for the AppleScript (JXA) read backend. osascript is always mocked."""
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from things_mcp import as_reader


def _item(uuid, title="t", type="to-do", status="open", **kw):
    base = {"uuid": uuid, "type": type, "title": title, "status": status, "notes": "",
            "tags": [], "start_date": None, "deadline": None, "created": None,
            "modified": None, "stop_date": None, "project": None, "area": None}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _clear_caches():
    as_reader._QUERY_CACHE.clear()
    as_reader._CACHE.clear()
    yield
    as_reader._QUERY_CACHE.clear()
    as_reader._CACHE.clear()


def fake_osa(data):
    """Return an _osa replacement serving `data[(kind, name_or_id)]` -> items."""
    calls = []

    def _osa(script, arg, timeout=60):
        calls.append(arg)
        spec = json.loads(arg) if arg.startswith("{") else {"kind": "get", "id": arg}
        key = (spec["kind"], spec.get("name") or spec.get("id"))
        if spec["kind"] == "get":
            return data.get(key)
        return data.get(key, [])

    _osa.calls = calls
    return _osa


class TestOsa:
    def test_nonzero_exit_raises_with_stderr(self):
        with patch("subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = "Not authorized to send Apple events"
            with pytest.raises(as_reader.ThingsReadError, match="Not authorized"):
                as_reader._osa("x", "y")

    def test_timeout_raises_readable_error(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("osascript", 1)):
            with pytest.raises(as_reader.ThingsReadError, match="Timed out"):
                as_reader._osa("x", "y")

    def test_parses_json_stdout(self):
        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '[{"uuid": "a"}]'
            assert as_reader._osa("x", "y") == [{"uuid": "a"}]


class TestLists:
    def test_inbox_sets_start(self):
        with patch.object(as_reader, "_osa", fake_osa({("list", "Inbox"): [_item("a")]})):
            [todo] = as_reader.inbox()
        assert todo["start"] == "Inbox"

    def test_query_results_are_not_shared_between_callers(self):
        osa = fake_osa({("list", "Inbox"): [_item("a")]})
        with patch.object(as_reader, "_osa", osa):
            as_reader.inbox()[0]["title"] = "mutated"
            before = len(osa.calls)
            assert as_reader.inbox()[0]["title"] == "t"
        assert len(osa.calls) == before  # second call served from cache


class TestProjectsAndGet:
    def _data(self):
        return {
            ("projects", None): [_item("p1", type="project"), _item("p2", type="project")],
            ("list", "Someday"): [_item("p2", type="project")],
            ("areas", None): [{"uuid": "a1", "type": "area", "title": "Home", "tags": []}],
            ("tags", None): [],
        }

    def test_projects_carry_someday_start(self):
        with patch.object(as_reader, "_osa", fake_osa(self._data())):
            by_id = {p["uuid"]: p["start"] for p in as_reader.projects()}
        assert by_id == {"p1": "Anytime", "p2": "Someday"}

    def test_projects_start_filter(self):
        with patch.object(as_reader, "_osa", fake_osa(self._data())):
            assert [p["uuid"] for p in as_reader.projects(start="Someday")] == ["p2"]

    def test_get_primes_cache_once_for_projects_and_areas(self):
        osa = fake_osa(self._data())
        with patch.object(as_reader, "_osa", osa):
            assert as_reader.get("a1")["title"] == "Home"
            assert as_reader.get("p1")["type"] == "project"
            n = len(osa.calls)
            as_reader.get("p2")
        assert len(osa.calls) == n

    def test_get_unknown_returns_none(self):
        with patch.object(as_reader, "_osa", fake_osa(self._data())):
            assert as_reader.get("nope") is None


class TestTasksFilters:
    def _patch(self):
        today = datetime.now()
        old = (today - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        new = (today - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        return patch.object(as_reader, "_osa", fake_osa({
            ("all_todos", None): [
                _item("t1", project="p1", tags=["x"], created=new, deadline="2030-01-01"),
                _item("t2", area="a1", created=old),
            ],
            ("projects", None): [_item("p1", type="project", created=old)],
            ("list", "Someday"): [],
            ("list", "Logbook"): [
                _item("l1", status="completed", stop_date="2026-01-05 10:00:00"),
                _item("l2", status="canceled", stop_date="2026-02-05 10:00:00"),
            ],
        }))

    def test_default_is_open_only(self):
        with self._patch():
            assert {i["uuid"] for i in as_reader.tasks()} == {"t1", "t2", "p1"}

    def test_status_completed_and_canceled_come_from_logbook(self):
        with self._patch():
            assert [i["uuid"] for i in as_reader.tasks(status="completed")] == ["l1"]
            assert [i["uuid"] for i in as_reader.tasks(status="canceled")] == ["l2"]

    def test_status_none_means_any(self):
        with self._patch():
            assert len(as_reader.tasks(status=None)) == 5

    def test_type_project_tag_area_filters(self):
        with self._patch():
            assert [i["uuid"] for i in as_reader.tasks(type="project")] == ["p1"]
            assert [i["uuid"] for i in as_reader.tasks(project="p1")] == ["t1"]
            assert [i["uuid"] for i in as_reader.tasks(tag="x")] == ["t1"]
            assert [i["uuid"] for i in as_reader.tasks(area="a1")] == ["t2"]

    def test_todos_excludes_projects(self):
        with self._patch():
            assert {i["uuid"] for i in as_reader.todos()} == {"t1", "t2"}

    def test_last_window(self):
        with self._patch():
            assert [i["uuid"] for i in as_reader.last("3d")] == ["t1"]

    def test_stop_date_operator(self):
        with self._patch():
            assert [i["uuid"] for i in as_reader.tasks(status="completed", stop_date=">=2026-01-01")] == ["l1"]
            assert as_reader.tasks(status="completed", stop_date=">2026-06-01") == []

    def test_deadline_future(self):
        with self._patch():
            assert [i["uuid"] for i in as_reader.tasks(deadline="future")] == ["t1"]

    def test_search_matches_title_and_notes_case_insensitively(self):
        data = {("all_todos", None): [_item("t1", title="Buy MILK"), _item("t2", notes="call milk co")],
                ("projects", None): [], ("list", "Someday"): [], ("list", "Logbook"): []}
        with patch.object(as_reader, "_osa", fake_osa(data)):
            assert {i["uuid"] for i in as_reader.search("milk")} == {"t1", "t2"}


class TestUnsupported:
    def test_headings_are_empty(self):
        assert as_reader.tasks(type="heading") == []
        assert as_reader.todos(heading="h1") == []


class TestToken:
    def test_unset_is_none(self, monkeypatch):
        monkeypatch.delenv("THINGS_AUTH_TOKEN", raising=False)
        assert as_reader.token() is None

    def test_unsubstituted_manifest_placeholder_is_none(self, monkeypatch):
        monkeypatch.setenv("THINGS_AUTH_TOKEN", "${user_config.auth_token}")
        assert as_reader.token() is None

    def test_value_is_returned_stripped(self, monkeypatch):
        monkeypatch.setenv("THINGS_AUTH_TOKEN", "  abc123 ")
        assert as_reader.token() == "abc123"


class TestInvalidation:
    def test_invalidate_clears_both_caches(self):
        osa = fake_osa({("list", "Inbox"): [_item("a")]})
        with patch.object(as_reader, "_osa", osa):
            as_reader.inbox()
            as_reader._CACHE["x"] = (0, {})
            before = len(osa.calls)
            as_reader.invalidate()
            as_reader.inbox()
        assert len(osa.calls) > before and not as_reader._CACHE

    def test_url_write_invalidates_reads(self):
        from things_mcp import url_scheme
        with patch.object(as_reader, "_osa", fake_osa({("list", "Inbox"): [_item("a")]})) as osa_patch:
            as_reader.inbox()
            assert as_reader._QUERY_CACHE
            with patch("subprocess.run"), patch.object(url_scheme.things, "invalidate", as_reader.invalidate, create=True):
                url_scheme.execute_url("things:///add?title=x")
            assert not as_reader._QUERY_CACHE


class TestListTypesAndSomedayChildren:
    def _data(self):
        return {
            ("list", "Someday"): [_item("p1", title="Someday proj"), _item("t9", title="loose todo")],
            ("projects", None): [_item("p1", type="project")],
            ("list", "Anytime"): [_item("t1")],
            ("project_todos", "p1"): [_item("c1", project="p1"), _item("c2", project="p1", status="completed")],
        }

    def test_projects_in_lists_are_typed_project(self):
        with patch.object(as_reader, "_osa", fake_osa(self._data())):
            by_id = {i["uuid"]: i["type"] for i in as_reader.someday()}
        assert by_id == {"p1": "project", "t9": "to-do"}

    def test_anytime_includes_open_children_of_someday_projects(self):
        with patch.object(as_reader, "_osa", fake_osa(self._data())):
            items = as_reader.anytime()
        assert {i["uuid"] for i in items} == {"t1", "c1"}  # completed child excluded
        assert next(i for i in items if i["uuid"] == "c1")["start"] == "Anytime"
