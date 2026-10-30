from vibe_code.runtime.diagnostics import parse_diagnostics, redact_diagnostics


def test_parse_python_traceback_and_gcc_location(tmp_path):
    target = tmp_path / "src" / "main.cpp"
    target.parent.mkdir()
    target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    py = tmp_path / "app.py"
    py.write_text("a\nb\nc\n", encoding="utf-8")
    log = f'  File "{py}", line 2, in run\n{target}:3:4: error: bad'
    locations = parse_diagnostics(log, tmp_path)
    assert [(item.path, item.line) for item in locations] == [("app.py", 2), ("src/main.cpp", 3)]
    assert "2: b" in locations[0].source_excerpt


def test_rejects_outside_missing_sensitive_and_invalid_lines(tmp_path):
    (tmp_path / "main.py").write_text("x\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.py"
    outside.write_text("x\n", encoding="utf-8")
    log = (
        f"{tmp_path / 'main.py'}:9:1: error\n"
        f"{tmp_path / '.env'}:1: error\n"
        f"{outside}:1: error\n"
        f"{tmp_path / 'missing.py'}:1: error"
    )
    assert parse_diagnostics(log, tmp_path) == ()


def test_rejects_symlinked_source(tmp_path):
    actual = tmp_path / "actual.py"
    actual.write_text("x\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    link.symlink_to(actual)
    assert parse_diagnostics(f"{link}:1: error", tmp_path) == ()


def test_redacts_common_credentials():
    value = redact_diagnostics("api_key=abc123 Authorization: Bearer tokenvalue password: hunter2")
    assert "abc123" not in value
    assert "tokenvalue" not in value
    assert "hunter2" not in value
    assert "[REDACTED]" in value



def test_rejects_symlinked_parent_directory(tmp_path):
    outside = tmp_path.parent / "outside-src"
    outside.mkdir()
    target = outside / "main.py"
    target.write_text("x\n", encoding="utf-8")
    link_dir = tmp_path / "linked"
    link_dir.symlink_to(outside, target_is_directory=True)
    assert parse_diagnostics(f"{link_dir / 'main.py'}:1: error", tmp_path) == ()


def test_redacts_credentials_from_source_excerpt(tmp_path):
    target = tmp_path / "main.py"
    target.write_text("api_key=very-secret-value\n", encoding="utf-8")
    locations = parse_diagnostics(f"{target}:1: error", tmp_path)
    assert len(locations) == 1
    assert "very-secret-value" not in locations[0].source_excerpt
    assert "[REDACTED]" in locations[0].source_excerpt
