from pathlib import Path, PurePosixPath

from vibe_code.context.models import ContextRequest
from vibe_code.context.service import ContextService
from vibe_code.context.settings import ContextSettings, estimate_tokens


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_settings_load_budget_exclusions_and_vibeignore(tmp_path):
    write(tmp_path, ".vibe-code/context.json", '{"token_budget": 4000, "exclude": ["docs/", "*.lock"]}')
    write(tmp_path, ".vibeignore", "# comment\nfixtures/big/*\n")

    settings = ContextSettings.load(tmp_path)

    assert settings.token_budget == 4000
    assert settings.is_excluded(PurePosixPath("docs/guide.md"))
    assert settings.is_excluded(PurePosixPath("poetry.lock"))
    assert settings.is_excluded(PurePosixPath("fixtures/big/data.json"))
    assert not settings.is_excluded(PurePosixPath("src/docs.py"))
    assert settings.errors == ()


def test_invalid_settings_fall_back_with_warnings(tmp_path):
    write(tmp_path, ".vibe-code/context.json", '{"token_budget": 5}')
    assert ContextSettings.load(tmp_path).token_budget == 12_000
    assert ContextSettings.load(tmp_path).errors
    write(tmp_path, ".vibe-code/context.json", "{broken")
    assert ContextSettings.load(tmp_path).errors


def test_context_respects_exclusions_rules_and_redacts_secrets(tmp_path):
    write(tmp_path, "AGENTS.md", "Always use type hints.\n")
    write(tmp_path, ".vibeignore", "generated/\n")
    write(tmp_path, "generated/client.py", "def login():\n    pass\n")
    write(tmp_path, "login.py", 'def login():\n    token = "ghp_' + "a" * 36 + '"\n    return token\n')

    pack = ContextService().build(ContextRequest("fix login", tmp_path, 2000))

    names = [item.path.name for item in pack.items]
    assert names[0] == "AGENTS.md"
    assert "client.py" not in names
    login = next(item for item in pack.items if item.path.name == "login.py")
    assert "ghp_" not in login.content
    assert "secrets redacted" in login.reason
    assert pack.redactions == 1
    assert "secrets redacted" in pack.summary()


def test_token_estimate_is_conservative_for_code():
    code = "def add(a: int, b: int) -> int:\n    return a + b  # sum\n"
    assert estimate_tokens(code) >= len(code) // 4
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2
