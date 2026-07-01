from pathlib import Path

from monitor.lib import session_artifacts


def test_normalize_session_identifier_sanitizes_input() -> None:
    """Verify session identifiers are safe for filesystem paths."""
    assert session_artifacts.normalize_session_identifier("abc/def 123") == "abc_def_123"


def test_build_session_folder_name_includes_timestamp_and_identifier() -> None:
    """Verify folder names combine timestamp and normalized session id."""
    assert session_artifacts.build_session_folder_name("20260101_12_34", "abc/def") == "20260101_12_34_abc_def"


def test_ensure_session_folder_creates_folder(tmp_path, monkeypatch) -> None:
    """Verify the session folder is created under the Monitor sessions root."""
    monkeypatch.setattr(session_artifacts.appdirs, "user_config_dir", lambda _name: str(tmp_path))
    paths = session_artifacts.ensure_session_folder("20260101_12_34", "abc")
    assert paths.root == tmp_path / "sessions"
    assert paths.folder == tmp_path / "sessions" / "20260101_12_34_abc"
    assert paths.folder.is_dir()


def test_append_log_entry_appends_without_overwriting(tmp_path, monkeypatch) -> None:
    """Verify log entries append and preserve prior content."""
    monkeypatch.setattr(session_artifacts.appdirs, "user_config_dir", lambda _name: str(tmp_path))
    paths = session_artifacts.ensure_session_folder("20260101_12_34", "abc")
    session_artifacts.append_log_entry(paths, "start", "first")
    session_artifacts.append_log_entry(paths, "update", "second", "body text")
    log_text = paths.log.read_text(encoding="utf-8")
    assert "## [" in log_text
    assert "start | first" in log_text
    assert "update | second" in log_text
    assert "body text" in log_text


def test_list_session_folders_returns_sorted_entries(tmp_path, monkeypatch) -> None:
    """Verify session folders are returned sorted lexicographically."""
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "20260101_12_34_a").mkdir()
    (root / "20260102_12_34_b").mkdir()
    monkeypatch.setattr(session_artifacts.appdirs, "user_config_dir", lambda _name: str(tmp_path))
    folders = session_artifacts.list_session_folders()
    assert folders == [root / "20260101_12_34_a", root / "20260102_12_34_b"]


def test_get_most_recent_session_folder_returns_latest(tmp_path, monkeypatch) -> None:
    """Verify the newest session folder is chosen by lexicographic order."""
    root = tmp_path / "sessions"
    root.mkdir()
    older = root / "20260101_12_34_a"
    newer = root / "20260102_12_34_b"
    older.mkdir()
    newer.mkdir()
    monkeypatch.setattr(session_artifacts.appdirs, "user_config_dir", lambda _name: str(tmp_path))
    assert session_artifacts.get_most_recent_session_folder() == newer


def test_list_most_recent_session_folders_returns_limit_and_order(tmp_path, monkeypatch) -> None:
    """Verify recent session folders are returned newest-first and capped."""
    root = tmp_path / "sessions"
    root.mkdir()
    for name in [
        "20260101_12_34_a",
        "20260102_12_34_b",
        "20260103_12_34_c",
        "20260104_12_34_d",
        "20260105_12_34_e",
        "20260106_12_34_f",
    ]:
        (root / name).mkdir()
    monkeypatch.setattr(session_artifacts.appdirs, "user_config_dir", lambda _name: str(tmp_path))
    folders = session_artifacts.list_most_recent_session_folders(limit=5)
    assert folders == [
        root / "20260106_12_34_f",
        root / "20260105_12_34_e",
        root / "20260104_12_34_d",
        root / "20260103_12_34_c",
        root / "20260102_12_34_b",
    ]
