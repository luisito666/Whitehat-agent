"""Skills por cliente: engagement.skills_dirs anade dirs extra al rol."""
from pathlib import Path

import yaml


def _make_skill(root: Path, role: str, marker: str) -> None:
    d = root / "skills" / role
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.md").write_text(marker, encoding="utf-8")


def _write_engagement(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "engagement.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def _valid_eng(skills_dirs=None):
    return {
        "engagement_id": "lab-2026-001",
        "client": {"name": "Cliente Demo"},
        "authorization": {"reference": "REF-001", "valid_from": "2026-01-01",
                          "valid_until": "2026-12-31"},
        "scope": {"allowed_targets": ["127.0.0.1/32"]},
        "rules_of_engagement": {"allowed_techniques": ["metasploit-module"]},
        **({"skills_dirs": skills_dirs} if skills_dirs else {}),
    }


def test_no_engagement_or_no_dirs_keeps_repo_skills(tmp_path, monkeypatch):
    _make_skill(tmp_path, "exploit", "REPOSKILL")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.delenv("PENTEST_ENGAGEMENT_FILE", raising=False)
    import os

    cwd_eng = Path.cwd() / "engagement.yaml"
    had = cwd_eng.exists()
    if had:
        cwd_eng.rename(tmp_path / "engagement.bak")

    from pentest_agent.skills import load_skills

    try:
        assert "REPOSKILL" in load_skills("exploit")
    finally:
        if had:
            (tmp_path / "engagement.bak").rename(cwd_eng)


def test_engagement_skills_dirs_appended(tmp_path, monkeypatch):
    _make_skill(tmp_path, "exploit", "REPOSKILL")
    client_dir = tmp_path / "client-packs" / "acme"
    (client_dir / "exploit").mkdir(parents=True)
    (client_dir / "exploit" / "z-runbook.md").write_text("ACME-RUNBOOK", encoding="utf-8")
    # dir de otro rol en el pack: no debe filtrar en exploit
    (client_dir / "recon").mkdir(parents=True)
    (client_dir / "recon" / "a.md").write_text("ACME-RECON", encoding="utf-8")

    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setenv(
        "PENTEST_ENGAGEMENT_FILE",
        str(_write_engagement(tmp_path, _valid_eng(skills_dirs=[str(client_dir)]))),
    )

    from pentest_agent.skills import load_skills

    out = load_skills("exploit")
    assert "REPOSKILL" in out and "ACME-RUNBOOK" in out
    assert "ACME-RECON" not in out          # aislamiento por rol
    assert out.index("REPOSKILL") < out.index("ACME-RUNBOOK")  # repo primero


def test_invalid_dir_in_engagement_is_skipped(tmp_path, monkeypatch):
    _make_skill(tmp_path, "vuln", "REPOSKILL2")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(_write_engagement(tmp_path, _valid_eng(skills_dirs=["/no/existe/acme"]))),
    )

    from pentest_agent.skills import load_skills

    out = load_skills("vuln")
    assert "REPOSKILL2" in out and "ACME" not in out


def test_invalid_engagement_keeps_repo_skills(tmp_path, monkeypatch):
    """Engagement invalido NO debe botar el arranque del worker: degrada a
    skills de repo (las tools ofensivas ya fail-closed por su propio gate)."""
    _make_skill(tmp_path, "exploit", "REPOSKILL3")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    bad = tmp_path / "engagement.yaml"
    bad.write_text("engagement_id: x\nclient: {}\n", encoding="utf-8")  # incompleto
    monkeypatch.setenv("PENTEST_ENGAGEMENT_FILE", str(bad))

    from pentest_agent.skills import load_skills

    assert "REPOSKILL3" in load_skills("exploit")
