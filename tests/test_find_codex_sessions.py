from __future__ import annotations

import json
from pathlib import Path

from tools.find_codex_sessions import cwd_matches_project, find_sessions, read_session_metadata


def _write_rollout(path: Path, records: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            if isinstance(record, str):
                stream.write(record + "\n")
            else:
                stream.write(json.dumps(record) + "\n")


def _session_meta(*, cwd: str, session_id: str = "session-1", version: str = "0.0-test") -> dict[str, object]:
    return {
        "type": "session_meta",
        "payload": {
            "id": session_id,
            "cwd": cwd,
            "cli_version": version,
            "source": "cli",
        },
    }


def test_cwd_matching_supports_windows_and_posix_paths() -> None:
    assert cwd_matches_project(r"C:\work\Example", r"c:\WORK\example", mode="path")
    assert cwd_matches_project(r"C:\work\Example\.agent-worktrees\task", r"C:\work\Example", mode="path")
    assert cwd_matches_project("/srv/work/example", "/srv/work/example", mode="path")
    assert cwd_matches_project("/srv/work/example/.agent-worktrees/task", "/srv/work/example", mode="path")
    assert not cwd_matches_project("/srv/work/example-old", "/srv/work/example", mode="path")


def test_name_mode_matches_path_component_not_substring() -> None:
    assert cwd_matches_project("/srv/work/example", "example")
    assert cwd_matches_project("/srv/work/example/.agent-worktrees/task", "example")
    assert not cwd_matches_project("/srv/work/example-old", "example")


def test_find_sessions_scans_current_and_archive_and_survives_bad_json(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    current = codex_home / "sessions" / "2026" / "08" / "31" / "rollout-current.jsonl"
    archived = codex_home / "archived_sessions" / "rollout-archived.jsonl"
    broken = codex_home / "sessions" / "2026" / "08" / "31" / "rollout-broken.jsonl"
    other = codex_home / "sessions" / "2026" / "08" / "31" / "rollout-other.jsonl"

    _write_rollout(current, [_session_meta(cwd="/work/project-a", session_id="current")])
    _write_rollout(archived, [_session_meta(cwd="/work/project-a", session_id="archived")])
    _write_rollout(broken, ["{not-json"])
    _write_rollout(other, [_session_meta(cwd="/work/project-b", session_id="other")])

    matches, problems = find_sessions("project-a", codex_home=codex_home)

    assert {match.session_id for match in matches} == {"current", "archived"}
    assert {match.archived for match in matches} == {False, True}
    assert any("not valid UTF-8 JSON" in problem.reason for problem in problems)
    assert any("session_meta not found" in problem.reason for problem in problems)


def test_find_sessions_can_exclude_archive(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    _write_rollout(
        codex_home / "sessions" / "rollout-current.jsonl",
        [_session_meta(cwd="/work/project-a", session_id="current")],
    )
    _write_rollout(
        codex_home / "archived_sessions" / "rollout-archived.jsonl",
        [_session_meta(cwd="/work/project-a", session_id="archived")],
    )

    matches, _ = find_sessions("project-a", codex_home=codex_home, include_archived=False)

    assert [match.session_id for match in matches] == ["current"]


def test_metadata_reader_skips_bad_prefix_and_finds_session_meta(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-test.jsonl"
    _write_rollout(
        rollout,
        [
            "{broken",
            {"type": "event_msg", "payload": {"type": "turn_started"}},
            _session_meta(cwd="/work/project-a"),
        ],
    )

    payload, line_number, warnings = read_session_metadata(rollout)

    assert payload is not None
    assert payload["cwd"] == "/work/project-a"
    assert line_number == 3
    assert warnings == ["line 1 is not valid UTF-8 JSON"]


def test_metadata_reader_bounds_oversized_lines(tmp_path: Path) -> None:
    rollout = tmp_path / "rollout-large.jsonl"
    oversized = json.dumps({"type": "event_msg", "payload": {"blob": "x" * 2048}})
    _write_rollout(rollout, [oversized, _session_meta(cwd="/work/project-a")])

    payload, line_number, warnings = read_session_metadata(rollout, max_line_bytes=128)

    assert payload is not None
    assert payload["cwd"] == "/work/project-a"
    assert line_number == 2
    assert warnings == ["line 1 exceeds metadata line limit"]


def test_missing_codex_home_is_reported_not_raised(tmp_path: Path) -> None:
    matches, problems = find_sessions("project-a", codex_home=tmp_path / "missing")

    assert matches == []
    assert [problem.reason for problem in problems] == ["no Codex session directories found"]
