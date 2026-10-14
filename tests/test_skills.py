from __future__ import annotations

from vibe_code.skills.service import SkillService


def test_skill_service_loads_only_relevant_skill(tmp_path):
    root = tmp_path / ".vibe-code" / "skills"
    (root / "desktop-ui").mkdir(parents=True)
    (root / "debugging").mkdir(parents=True)
    (root / "desktop-ui" / "SKILL.md").write_text(
        "---\nname: desktop-ui\ndescription: Build desktop UI screens and layouts\n---\n"
        "# UI skill\nUse reusable widgets.\n",
        encoding="utf-8",
    )
    (root / "debugging" / "SKILL.md").write_text(
        "---\nname: debugging\ndescription: Diagnose crashes and errors\n---\n"
        "# Debugging\nInspect logs first.\n",
        encoding="utf-8",
    )

    skills = SkillService().load_for_prompt(tmp_path, "improve the UI layout screen")
    assert len(skills) == 1
    assert skills[0].name == "desktop-ui"
    assert "reusable widgets" in skills[0].content


def test_skill_service_ignores_irrelevant_skills(tmp_path):
    root = tmp_path / ".vibe-code" / "skills" / "packaging"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\nname: packaging\ndescription: Package and release apps\n---\n",
        encoding="utf-8",
    )
    assert SkillService().load_for_prompt(tmp_path, "change the window title") == ()
