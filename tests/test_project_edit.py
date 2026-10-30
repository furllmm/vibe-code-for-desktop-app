import hashlib
import json

import pytest

from vibe_code.changes import ChangeManager
from vibe_code.context.models import ContextItem, ContextPack
from vibe_code.editor.project_edit import ProjectEditSession
from vibe_code.providers.base import ProviderResponse
from vibe_code.tools.filesystem import WorkspaceFS
from vibe_code.workspace import Workspace


class FakeContext:
    def build(self, request):
        path = request.workspace / "src" / "main.py"
        return ContextPack((ContextItem(path, "file", 10, "match", path.read_text(), 1, 1),), 10)


class FakeProvider:
    def __init__(self, content):
        self.content, self.requests = content, []

    def complete(self, request):
        self.requests.append(request)
        return ProviderResponse(self.content)


def proposal(path, original, updated):
    return json.dumps({"files": [{
        "path": path, "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "content": updated,
    }]})


def setup_workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n")
    return Workspace(tmp_path)


def test_proposal_is_read_only_and_apply_is_rollbackable(tmp_path):
    workspace = setup_workspace(tmp_path)
    original = "print('hello')\n"
    provider = FakeProvider(proposal("src/main.py", original, "print('hi')\n"))
    session = ProjectEditSession(provider, workspace, FakeContext())
    edit = session.propose("Change greeting")
    assert (tmp_path / "src/main.py").read_text() == original
    assert "print('hi')" in edit.unified_diff()
    manager = ChangeManager(WorkspaceFS(tmp_path))
    change_set = session.apply(edit, manager)
    assert len(change_set.changes) == 1
    manager.rollback(change_set.id)
    assert (tmp_path / "src/main.py").read_text() == original


@pytest.mark.parametrize("path", ["../outside.py", "/tmp/outside.py", "other.py"])
def test_proposal_rejects_targets_outside_retrieved_context(tmp_path, path):
    workspace = setup_workspace(tmp_path)
    provider = FakeProvider(proposal(path, "print('hello')\n", "x"))
    with pytest.raises(ValueError):
        ProjectEditSession(provider, workspace, FakeContext()).propose("Change")


@pytest.mark.parametrize("payload", [
    {"files": [{"path": "src/main.py", "original_sha256": "bad", "content": "x"}]},
    {"files": [{"path": "src/main.py", "original_sha256": "a", "content": "x"},
               {"path": "src/main.py", "original_sha256": "a", "content": "y"}]},
    {"files": [{"path": "src/main.py", "original_sha256": "a", "content": "x", "extra": 1}]},
])
def test_invalid_provider_proposals_are_rejected(tmp_path, payload):
    workspace = setup_workspace(tmp_path)
    session = ProjectEditSession(FakeProvider(json.dumps(payload)), workspace, FakeContext())
    with pytest.raises(ValueError):
        session.propose("Change")


def test_stale_hash_prevents_apply(tmp_path):
    workspace = setup_workspace(tmp_path)
    original = "print('hello')\n"
    session = ProjectEditSession(
        FakeProvider(proposal("src/main.py", original, "print('hi')\n")),
        workspace, FakeContext()
    )
    edit = session.propose("Change")
    target = tmp_path / "src/main.py"
    target.write_text("external")
    manager = ChangeManager(WorkspaceFS(tmp_path))
    with pytest.raises(RuntimeError, match="changed after preview"):
        session.apply(edit, manager)
    assert target.read_text() == "external"


def test_write_many_preflights_all_files_before_writing(tmp_path):
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    manager = ChangeManager(WorkspaceFS(tmp_path))
    with pytest.raises(RuntimeError):
        manager.write_many({
            "a.py": ("A", hashlib.sha256(b"a").hexdigest()),
            "b.py": ("B", "stale"),
        })
    assert (tmp_path / "a.py").read_text() == "a"
    assert (tmp_path / "b.py").read_text() == "b"


def test_write_many_records_one_rollback_set(tmp_path):
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    manager = ChangeManager(WorkspaceFS(tmp_path))
    changes = manager.write_many({
        "a.py": ("A", hashlib.sha256(b"a").hexdigest()),
        "b.py": ("B", hashlib.sha256(b"b").hexdigest()),
    })
    assert len(changes.changes) == 2
    manager.rollback(changes.id)
    assert (tmp_path / "a.py").read_text() == "a"
    assert (tmp_path / "b.py").read_text() == "b"


def test_instruction_limit_and_noop_proposal(tmp_path):
    workspace = setup_workspace(tmp_path)
    session = ProjectEditSession(
        FakeProvider(proposal("src/main.py", "print('hello')\n", "print('hello')\n")),
        workspace, FakeContext()
    )
    with pytest.raises(ValueError, match="4 KiB"):
        session.propose("x" * (4 * 1024 + 1))
    with pytest.raises(ValueError, match="no effective"):
        session.propose("Change")

def test_rollback_preflights_entire_project_change_set(tmp_path):
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    manager = ChangeManager(WorkspaceFS(tmp_path))
    changes = manager.write_many({
        "a.py": ("A", hashlib.sha256(b"a").hexdigest()),
        "b.py": ("B", hashlib.sha256(b"b").hexdigest()),
    })
    (tmp_path / "b.py").write_text("external")
    with pytest.raises(RuntimeError, match="changed after the recorded write"):
        manager.rollback(changes.id)
    assert (tmp_path / "a.py").read_text() == "A"
    assert (tmp_path / "b.py").read_text() == "external"

def test_write_many_rejects_symlink_targets(tmp_path):
    (tmp_path / "real.py").write_text("original")
    (tmp_path / "link.py").symlink_to(tmp_path / "real.py")
    manager = ChangeManager(WorkspaceFS(tmp_path))
    with pytest.raises(PermissionError, match="Symlink"):
        manager.write_many({
            "link.py": ("changed", hashlib.sha256(b"original").hexdigest())
        })
    assert (tmp_path / "real.py").read_text() == "original"
