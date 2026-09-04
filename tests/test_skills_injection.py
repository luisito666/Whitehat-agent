"""Skills se inyectan en el prompt de cada worker (A2A e in-process)."""
from pathlib import Path


def _make_skill(root: Path, role: str, marker: str) -> None:
    d = root / "skills" / role
    d.mkdir(parents=True, exist_ok=True)
    (d / "z-skill.md").write_text(marker, encoding="utf-8")


def test_a2a_executor_injects_skills(tmp_path, monkeypatch):
    _make_skill(tmp_path, "recon", "RECONSKILL123")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")

    captured = {}

    def fake_react_agent(llm, tools, prompt_txt):
        captured["prompt"] = prompt_txt
        captured["tools"] = tools
        return object()

    monkeypatch.setattr("pentest_agent.a2a_server._react_agent", fake_react_agent)
    import pentest_agent.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda: None)

    from pentest_agent.a2a_server import ReactAgentExecutor

    ex = ReactAgentExecutor("recon")
    ex._get_agent()
    assert "RECONSKILL123" in captured["prompt"]
    assert "Guia de procedimiento" in captured["prompt"]
    # el prompt base va primero, las skills despues
    assert captured["prompt"].index("recon_agent") < captured["prompt"].index("RECONSKILL123")


def test_a2a_executor_without_skills_uses_base_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")
    captured = {}

    def fake_react_agent(llm, tools, prompt_txt):
        captured["prompt"] = prompt_txt
        return object()

    monkeypatch.setattr("pentest_agent.a2a_server._react_agent", fake_react_agent)
    import pentest_agent.llm as llm_mod

    monkeypatch.setattr(llm_mod, "get_llm", lambda: None)

    from pentest_agent.a2a_server import ReactAgentExecutor

    ReactAgentExecutor("vuln")._get_agent()
    assert "Guia de procedimiento" not in captured["prompt"]
    assert "vuln_agent" in captured["prompt"]


def test_build_team_injects_skills(tmp_path, monkeypatch):
    _make_skill(tmp_path, "vuln", "VULNSKILL777")
    monkeypatch.setattr("pentest_agent.skills.SKILLS_ROOT", tmp_path / "skills")

    captured = []

    def fake_react_agent(llm, tools, prompt_txt, name=None):
        captured.append(prompt_txt)
        return object()

    monkeypatch.setattr("pentest_agent.agents._react_agent", fake_react_agent)
    monkeypatch.setattr("pentest_agent.agents.get_llm", lambda: None)

    class _FakeSup:
        def __init__(self, **kw):
            pass

        def compile(self):
            return object()

    monkeypatch.setattr("pentest_agent.agents.create_supervisor", lambda **kw: _FakeSup())

    from pentest_agent.agents import build_team

    build_team()
    assert any("VULNSKILL777" in p for p in captured)
