"""Tests del matching CPE exacto (feat: cpe-version-matching).

Cubre: normalizacion 2.2->2.3, matching por criteria con rangos
(versionEndIncluding/Excluding), parseo de criteria en parse_nvd_response,
y find_cves en sus tres modos (cpe_exact, keyword, keyword_fallback)
con NVD mockeada (sin red).
"""
from __future__ import annotations

import json

import pytest

from pentest_agent.tools.vuln import (
    _cpe_exact_matches,
    _criteria_strings,
    cpe_matches_target,
    find_cves,
    normalize_cpe,
    parse_nvd_response,
    search_nvd,
    search_nvd_cpe,
)

SSH_96 = "cpe:/a:openbsd:openssh:9.6p1"
SSH_96_23 = "cpe:2.3:a:openbsd:openssh:9.6p1:*:*:*:*:*:*:*"
NGINX_125 = "cpe:2.3:a:nginx:nginx:1.25.3:*:*:*:*:*:*:*"


# ---------------------------------------------------------------------------
# normalize_cpe
# ---------------------------------------------------------------------------

class TestNormalizeCpe:
    def test_cpe22_con_version(self):
        assert normalize_cpe(SSH_96) == SSH_96_23

    def test_cpe22_sin_version(self):
        # cpe:/a:apache:httpd -> version y resto '*'
        out = normalize_cpe("cpe:/a:apache:httpd")
        assert out == "cpe:2.3:a:apache:httpd:*:*:*:*:*:*:*:*"

    def test_cpe22_con_update_edition(self):
        out = normalize_cpe("cpe:/a:vendor:prod:1.0:u1")
        assert out.startswith("cpe:2.3:a:vendor:prod:1.0:u1:")
        assert out.count(":") == 12

    def test_cpe23_pasa_padded(self):
        out = normalize_cpe("cpe:2.3:a:nginx:nginx:1.25.3")
        assert out == NGINX_125

    def test_cpe23_completo_se_respeta(self):
        assert normalize_cpe(NGINX_125) == NGINX_125

    def test_basura_devuelve_none(self):
        assert normalize_cpe("not a cpe") is None
        assert normalize_cpe("") is None
        assert normalize_cpe("cpe:/x:mal") is None


# ---------------------------------------------------------------------------
# cpe_matches_target
# ---------------------------------------------------------------------------

class TestCpeMatches:
    def test_match_exacto(self):
        assert cpe_matches_target(SSH_96_23, SSH_96_23)

    def test_criteria_con_wildcards_matchea(self):
        crit = "cpe:2.3:a:openbsd:openssh:*:*:*:*:*:*:*:*"
        assert cpe_matches_target(SSH_96_23, crit)

    def test_otra_version_no_matchea(self):
        crit = "cpe:2.3:a:openbsd:openssh:9.7p1:*:*:*:*:*:*:*"
        assert not cpe_matches_target(SSH_96_23, crit)

    def test_otro_producto_no_matchea(self):
        crit = "cpe:2.3:a:apache:httpd:2.4.49:*:*:*:*:*:*:*"
        assert not cpe_matches_target(SSH_96_23, crit)

    def test_rango_end_including(self):
        crit = "cpe:2.3:a:apache:log4j:2.0:*:*:*:*:*:*:*"
        # target 1.2 <= 2.15.0 -> dentro del rango
        assert cpe_matches_target(
            "cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*", crit,
            version_end_including="2.15.0")
        assert not cpe_matches_target(
            "cpe:2.3:a:apache:log4j:2.16.0:*:*:*:*:*:*:*", crit,
            version_end_including="2.15.0")

    def test_rango_end_excluding(self):
        crit = "cpe:2.3:a:apache:log4j:2.0:*:*:*:*:*:*:*"
        assert not cpe_matches_target(
            "cpe:2.3:a:apache:log4j:2.15.0:*:*:*:*:*:*:*", crit,
            version_end_excluding="2.15.0")
        assert cpe_matches_target(
            "cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*", crit,
            version_end_excluding="2.15.0")

    def test_version_no_numerica(self):
        crit = "cpe:2.3:a:openbsd:openssh:9.6p1:*:*:*:*:*:*:*"
        assert cpe_matches_target(SSH_96_23, crit)
        assert not cpe_matches_target(
            "cpe:2.3:a:openbsd:openssh:9.6p2:*:*:*:*:*:*:*", crit)


# ---------------------------------------------------------------------------
# criteria en parse_nvd_response
# ---------------------------------------------------------------------------

def _nvd_cve(cid="CVE-2024-1234", criteria=None, end_inc=None, end_exc=None):
    cpe_match = {"criteria": criteria or SSH_96_23, "vulnerable": True}
    if end_inc:
        cpe_match["versionEndIncluding"] = end_inc
    if end_exc:
        cpe_match["versionEndExcluding"] = end_exc
    return {"vulnerabilities": [{"cve": {
        "id": cid,
        "descriptions": [{"lang": "en", "value": "RCE critico en demo"}],
        "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}]},
        "references": [{"url": f"https://nvd.nist.gov/vuln/detail/{cid}"}],
        "published": "2024-01-01T00:00:00.000",
        "configurations": [{"nodes": [{"cpeMatch": [cpe_match]}]}],
    }}]}


class TestCriteriaExtraction:
    def test_vulnerable_cpes_presente(self):
        out = parse_nvd_response(_nvd_cve())
        assert out[0]["vulnerable_cpes"] == [SSH_96_23]

    def test_rango_como_sufijo(self):
        out = parse_nvd_response(_nvd_cve(end_inc="9.8p1"))
        assert out[0]["vulnerable_cpes"] == [f"{SSH_96_23} <= 9.8p1"]

    def test_sin_configurations(self):
        data = _nvd_cve()
        del data["vulnerabilities"][0]["cve"]["configurations"]
        out = parse_nvd_response(data)
        assert out[0]["vulnerable_cpes"] == []

    def test_cpe_exact_matches_true_false(self):
        data = _nvd_cve()
        cve = data["vulnerabilities"][0]["cve"]
        assert _cpe_exact_matches(cve, SSH_96_23)
        assert not _cpe_exact_matches(cve, "cpe:2.3:a:openbsd:openssh:9.7p1:*:*:*:*:*:*:*")

    def test_cpe_exact_matches_rango(self):
        cve = _nvd_cve(criteria="cpe:2.3:a:apache:log4j:2.0:*:*:*:*:*:*:*",
                       end_exc="2.15.0")["vulnerabilities"][0]["cve"]
        assert _cpe_exact_matches(cve, "cpe:2.3:a:apache:log4j:2.14.1:*:*:*:*:*:*:*")
        assert not _cpe_exact_matches(cve, "cpe:2.3:a:apache:log4j:2.15.0:*:*:*:*:*:*:*")


# ---------------------------------------------------------------------------
# find_cves (tool) con NVD mockeada
# ---------------------------------------------------------------------------

NVD_SSH_PAGE = {
    "vulnerabilities": [
        {"cve": {
            "id": "CVE-2024-1111",
            "descriptions": [{"lang": "en", "value": "OpenSSH 9.6p1 RCE"}],
            "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 9.1, "baseSeverity": "CRITICAL"}}]},
            "references": [],
            "published": "2024-02-02T00:00:00.000",
            "configurations": [{"nodes": [{"cpeMatch": [
                {"criteria": SSH_96_23, "vulnerable": True}]}]}],
        }},
        {"cve": {
            "id": "CVE-2024-2222",
            "descriptions": [{"lang": "en", "value": "OpenSSH 9.7p1 reg"}],
            "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 7.5, "baseSeverity": "HIGH"}}]},
            "references": [],
            "published": "2024-03-03T00:00:00.000",
            "configurations": [{"nodes": [{"cpeMatch": [
                {"criteria": "cpe:2.3:a:openbsd:openssh:9.7p1:*:*:*:*:*:*:*", "vulnerable": True}]}]}],
        }},
    ],
}


@pytest.fixture
def kev_cache(tmp_path, monkeypatch):
    """KEV cacheada para no tocar la red en tests."""
    import pentest_agent.tools.vuln as vuln_mod
    cache_file = tmp_path / "kev.json"
    cache_file.write_text(json.dumps(["CVE-2024-1111"]))
    monkeypatch.setattr(vuln_mod, "CACHE", cache_file)
    return cache_file


class TestFindCvesTool:
    def test_cpe_exact_filtra_version_vecina(self, kev_cache, monkeypatch):
        """El CVE de 9.7p1 NO debe aparecer buscando el CPE de 9.6p1."""
        monkeypatch.setattr("pentest_agent.tools.vuln._nvd_get", lambda p, timeout=30.0: NVD_SSH_PAGE)
        out = json.loads(find_cves.invoke({"query": "OpenSSH 9.6p1", "cpe": SSH_96}))
        assert out["match_mode"] == "cpe_exact"
        ids = [c["cve"] for c in out["cves"]]
        assert ids == ["CVE-2024-1111"]
        assert out["cves"][0]["kev"] is True
        assert out["cpe"] == SSH_96_23

    def test_keyword_sin_cpe(self, kev_cache, monkeypatch):
        monkeypatch.setattr("pentest_agent.tools.vuln._nvd_get", lambda p, timeout=30.0: NVD_SSH_PAGE)
        out = json.loads(find_cves.invoke({"query": "OpenSSH 9.6p1"}))
        assert out["match_mode"] == "keyword"
        assert len(out["cves"]) == 2  # keyword no filtra version

    def test_keyword_fallback(self, kev_cache, monkeypatch):
        """CPE valido, NVD sin matches exactos -> degrada a keyword marcado."""
        empty = {"vulnerabilities": []}
        calls = []

        def fake_nvd(params, timeout=30.0):
            calls.append(params)
            return empty if "cpeName" in params else NVD_SSH_PAGE

        monkeypatch.setattr("pentest_agent.tools.vuln._nvd_get", fake_nvd)
        out = json.loads(find_cves.invoke({"query": "OpenSSH 9.6p1", "cpe": SSH_96}))
        assert out["match_mode"] == "keyword_fallback"
        assert len(out["cves"]) == 2
        assert any("cpeName" in c for c in calls)

    def test_cpe_invalido_cae_a_keyword(self, kev_cache, monkeypatch):
        monkeypatch.setattr("pentest_agent.tools.vuln._nvd_get", lambda p, timeout=30.0: NVD_SSH_PAGE)
        out = json.loads(find_cves.invoke({"query": "nginx 1.25", "cpe": "garbage"}))
        assert out["match_mode"] == "keyword"

    def test_error_devuelve_json(self, kev_cache, monkeypatch):
        def boom(params, timeout=30.0):
            raise RuntimeError("network down")
        monkeypatch.setattr("pentest_agent.tools.vuln._nvd_get", boom)
        out = json.loads(find_cves.invoke({"query": "OpenSSH 9.6p1"}))
        assert "error" in out


# ---------------------------------------------------------------------------
# search_nvd_cpe: parametro correcto a la API
# ---------------------------------------------------------------------------

class TestSearchParams:
    def test_search_nvd_cpe_params(self, monkeypatch):
        seen = {}

        def fake_nvd(params, timeout=30.0):
            seen.update(params)
            # una sola pagina basta para el test
            return {"totalResults": len(NVD_SSH_PAGE["vulnerabilities"]),
                    "vulnerabilities": NVD_SSH_PAGE["vulnerabilities"]}

        monkeypatch.setattr("pentest_agent.tools.vuln._nvd_get", fake_nvd)
        search_nvd_cpe(SSH_96_23)
        assert seen["cpeName"] == SSH_96_23
        assert "virtualMatch" not in seen  # removido: la API real lo rechaza (404)

    def test_search_nvd_cpe_paginates(self, monkeypatch):
        pages = [
            {"totalResults": 3, "vulnerabilities": NVD_SSH_PAGE["vulnerabilities"]},
            {"totalResults": 3, "vulnerabilities": NVD_SSH_PAGE["vulnerabilities"][1:]},
        ]
        calls = []

        def fake_nvd(params, timeout=30.0):
            calls.append(params["startIndex"])
            return pages[len(calls) - 1]

        monkeypatch.setattr("pentest_agent.tools.vuln._nvd_get", fake_nvd)
        out = search_nvd_cpe(SSH_96_23)
        assert len(calls) == 2  # pidio la segunda pagina
        # 9.6p1 aparece en ambas paginas -> no debe duplicarse en el resultado
        ids = [f["cve"] for f in out]
        assert ids.count("CVE-2024-1111") == 1

    def test_search_nvd_keyword_params(self, monkeypatch):
        seen = {}

        def fake_nvd(params, timeout=30.0):
            seen.update(params)
            return {"vulnerabilities": []}

        monkeypatch.setattr("pentest_agent.tools.vuln._nvd_get", fake_nvd)
        search_nvd("OpenSSH 9.6")
        assert seen["keywordSearch"] == "OpenSSH 9.6"
