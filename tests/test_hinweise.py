"""Die Texte „Benutzung“ und „Datenschutz“ stimmen mit dem Verhalten und den Konstanten des Codes überein."""
import re
import tomllib
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import oa_bundle
import oa_hinweise
import oa_render

ORDNER = Path(__file__).resolve().parent.parent
APP = str(ORDNER / "app.py")


def _app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def _expander_text(at: AppTest, anfang: str) -> str:
    expander = next(e for e in at.expander if e.label.startswith(anfang))
    return "\n".join(m.value for m in expander.markdown)


def test_upload_grenze_kommt_aus_der_konfiguration_und_steht_im_text():
    konfig = tomllib.loads((ORDNER / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert oa_hinweise.upload_grenze_mb() == konfig["server"]["maxUploadSize"] == 5
    assert f"je hochgeladener Datei höchstens {konfig['server']['maxUploadSize']} MB" in oa_hinweise.benutzung()


def test_zip_grenzen_im_text_sind_die_des_codes():
    text = oa_hinweise.benutzung()
    assert f"höchstens {oa_bundle.MAX_DATEIEN} Dateien" in text
    assert "entpackt höchstens 25 MB" in text and oa_bundle.MAX_ENTPACKT_BYTES == 25_000_000
    assert "je Datei höchstens\n  8 MB" in text and oa_bundle.MAX_EINZEL_BYTES == 8_000_000


def test_zwischenspeicher_angaben_im_text_sind_die_der_dekoratoren():
    quelle = (ORDNER / "app.py").read_text(encoding="utf-8")
    # beide Zwischenspeicher der App nehmen Größe und Ablaufzeit aus oa_hinweise
    assert quelle.count("ttl=oa_hinweise.CACHE_TTL_SEKUNDEN") == 2
    assert "max_entries=oa_hinweise.CACHE_MAX_LADEN" in quelle and "max_entries=oa_hinweise.CACHE_MAX_BUENDELN" in quelle
    text = oa_hinweise.datenschutz()
    assert oa_hinweise.CACHE_TTL_SEKUNDEN == 600 and "verfällt nach 10 Minuten" in text
    assert f"höchstens {oa_hinweise.CACHE_MAX_LADEN} bzw.\n  {oa_hinweise.CACHE_MAX_BUENDELN} Einträge" in text


def test_datenschutz_nennt_den_cdn_host_den_die_seite_wirklich_laedt():
    host = re.search(r"https://([^/]+)/", oa_render.CDN).group(1)
    assert host == "cdn.jsdelivr.net"
    assert host in oa_hinweise.datenschutz() and host in oa_hinweise.benutzung()


def test_datenschutz_behauptet_keine_sitzungsbegrenzung_mehr():
    """Der Zwischenspeicher gilt über Sitzungen hinweg; „nur für die Sitzung“ wäre falsch."""
    assert "nur für diese Sitzung" not in (ORDNER / "app.py").read_text(encoding="utf-8")
    assert "nur für diese Sitzung" not in oa_hinweise.datenschutz()


def test_konfiguration_schaltet_die_nutzungsstatistik_aus_wie_der_text_sagt():
    konfig = tomllib.loads((ORDNER / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert konfig["browser"]["gatherUsageStats"] is False
    assert "`gatherUsageStats = false`" in oa_hinweise.datenschutz()


def test_app_schreibt_nichts_auf_die_festplatte_und_ruft_kein_netz_auf():
    """Der Datenschutztext sagt, die App schreibe nichts und sende nichts weiter: dann dürfen die Quelltexte das nicht tun."""
    verboten = re.compile(r"\b(write_text|write_bytes|requests|urlopen|urllib\.request|http\.client|socket|subprocess|tempfile|shutil|sqlite3|logging)\b|\bopen\([^)]*[\"'][wax]")
    for datei in [ORDNER / "app.py", *sorted(ORDNER.glob("oa_*.py"))]:
        for nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            if zeile.lstrip().startswith("#"):
                continue
            assert not verboten.search(zeile), f"{datei.name}:{nr}: {zeile.strip()}"


def test_app_zeigt_beide_expander_zugeklappt_mit_den_texten():
    at = _app()
    labels = [e.label for e in at.expander]
    assert "📖 Benutzung" in labels and "🔒 Datenschutz" in labels
    assert _expander_text(at, "📖") .strip() == oa_hinweise.benutzung().strip()
    assert _expander_text(at, "🔒").strip() == oa_hinweise.datenschutz().strip()


def test_texte_enthalten_kein_loses_dollarzeichen_das_streamlit_als_formel_deutet():
    """`$ref` steht immer in Code-Schreibweise; ein loses `$` würde Text zwischen zwei Dollarzeichen als Formel setzen."""
    for text in (oa_hinweise.benutzung(), oa_hinweise.datenschutz()):
        ohne_code = re.sub(r"`[^`]*`", "", text)
        assert "$" not in ohne_code


@pytest.mark.parametrize("text", [oa_hinweise.benutzung(), oa_hinweise.datenschutz()])
def test_texte_haben_echte_umlaute_statt_umschreibungen(text):
    umschreibungen = re.findall(r"\b(?:fuer|ueber|koennen|muessen|moeglich|zurueck|Groesse|waehlen|Pruefung|gueltig|Datei(?:en)?groesse)\b", text)
    assert umschreibungen == []
    assert any(umlaut in text for umlaut in "äöüß")  # echte Umlaute kommen vor (nicht jeder in jedem Text)
