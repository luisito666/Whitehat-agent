"""Tests del loader de skills por rol (markdown concatenado al prompt)."""
from pathlib import Path

import pytest


def _make_skill(root: Path, role: str, name: str, text: str) -> None:
    d = root / "skills" / role
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def test_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    from pentest_agent.skills import load_skills

    assert load_skills("recon") == ""


def test_concatenates_alphabetical(tmp_path, monkeypatch):
    _make_skill(tmp_path, "recon", "b-method.md", "## Metodo B")
    _make_skill(tmp_path, "recon", "a-method.md", "## Metodo A")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    from pentest_agent.skills import load_skills

    out = load_skills("recon")
    assert "Metodo A" in out and "Metodo B" in out
    assert out.index("Metodo A") < out.index("Metodo B")
    assert out.startswith("## Metodo A")


def test_ignores_non_md(tmp_path, monkeypatch):
    _make_skill(tmp_path, "recon", "note.txt", "x")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    from pentest_agent.skills import load_skills

    assert load_skills("recon") == ""


def test_roles_are_isolated(tmp_path, monkeypatch):
    _make_skill(tmp_path, "vuln", "a.md", "VULN-ONLY")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    from pentest_agent.skills import load_skills

    assert "VULN-ONLY" in load_skills("vuln")
    assert load_skills("recon") == ""


def test_real_repo_has_skills_for_all_roles():
    """El repo commitea skills para los 4 roles (recon, vuln, reporter, exploit)."""
    from pentest_agent.skills import SKILLS_ROOT, load_skills

    for role in ("recon", "vuln", "reporter", "exploit"):
        assert (SKILLS_ROOT / role).is_dir(), f"falta skills/{role}/"
        assert load_skills(role).strip(), f"skills/{role}/ vacio"
