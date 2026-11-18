"""HTML-Seite der Swagger UI: Einbettung der Spezifikation, feste Bibliotheksversion, Schalter."""
import base64
import json
import re

import pytest

import oa_render

SPEC = {"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": {}}


def _konfig(seite: str) -> dict:
    treffer = re.search(r"var konfig = (.*);\n", seite)
    assert treffer, "Konfiguration nicht gefunden"
    return json.loads(treffer.group(1))


def test_spezifikation_steht_unveraendert_in_der_seite():
    spec = {**SPEC, "x-text": "Ümläute – „Zitat“ & <b>fett</b> 日本"}
    assert _konfig(oa_render.html_seite(spec))["spec"] == spec


def test_json_fuer_script_enthaelt_keine_gefaehrlichen_zeichen_und_laesst_sich_zuruecklesen():
    wert = {"a": "</script><script>alert(1)</script>", "b": "x & y > z", "c": "zeile zwei drei"}
    text = oa_render.json_fuer_script(wert)
    for zeichen in "<>&  ":
        assert zeichen not in text
    assert json.loads(text) == wert


def test_beschreibung_mit_script_ende_beendet_den_skriptblock_nicht():
    spec = {**SPEC, "info": {"title": "t", "version": "1", "description": "</script><script>alert(1)</script>"}}
    seite = oa_render.html_seite(spec)
    assert "alert(1)" in seite  # als Text im JSON
    assert "</script><script>alert" not in seite
    # genau die beiden Skriptblöcke der Vorlage (Bibliothek und Start), keiner mehr
    assert seite.count("<script") == 2 and seite.count("</script>") == 2


def test_titel_wird_fuer_html_maskiert():
    seite = oa_render.html_seite(SPEC, titel='A <b>"&"</b>')
    assert "<title>A &lt;b&gt;&quot;&amp;&quot;&lt;/b&gt;</title>" in seite


def test_bibliothek_in_fester_version_ohne_latest():
    seite = oa_render.html_seite(SPEC)
    assert f"swagger-ui-dist@{oa_render.SWAGGER_UI_VERSION}/swagger-ui-bundle.js" in seite
    assert f"swagger-ui-dist@{oa_render.SWAGGER_UI_VERSION}/swagger-ui.css" in seite
    assert re.fullmatch(r"\d+\.\d+\.\d+", oa_render.SWAGGER_UI_VERSION)
    assert "@latest" not in seite


def test_try_it_out_aus_sendet_keine_anfragen_an_ein():
    assert _konfig(oa_render.html_seite(SPEC, try_it_out=False))["supportedSubmitMethods"] == []
    an = _konfig(oa_render.html_seite(SPEC, try_it_out=True))["supportedSubmitMethods"]
    assert {"get", "post", "put", "delete", "patch"} <= set(an)


@pytest.mark.parametrize("modus", oa_render.DOC_EXPANSION)
def test_doc_expansion_und_filter_kommen_an(modus):
    k = _konfig(oa_render.html_seite(SPEC, doc_expansion=modus, filter_leiste=False))
    assert k["docExpansion"] == modus and k["filter"] is False
    assert _konfig(oa_render.html_seite(SPEC, filter_leiste=True))["filter"] is True


def test_unbekannte_doc_expansion_wird_abgelehnt():
    with pytest.raises(ValueError):
        oa_render.html_seite(SPEC, doc_expansion="alles")


def test_data_url_ergibt_die_seite_zurueck_und_ist_text_html():
    seite = oa_render.html_seite({**SPEC, "x": "ä"})
    url = oa_render.als_data_url(seite)
    kopf, daten = url.split(",", 1)
    assert kopf == "data:text/html;charset=utf-8;base64"
    assert base64.b64decode(daten).decode("utf-8") == seite


@pytest.mark.parametrize(
    "titel,erwartet",
    [
        ("Sendungsverfolgung", "sendungsverfolgung.html"),
        ("Größe & Gewicht (v2)", "groesse-gewicht-v2.html"),
        ("Äpfel über Öl", "aepfel-ueber-oel.html"),
        ("!!!", "openapi.html"),
        ("", "openapi.html"),
    ],
)
def test_html_dateiname(titel, erwartet):
    assert oa_render.html_dateiname({"info": {"title": titel}}) == erwartet


def test_html_dateiname_ohne_info_block():
    assert oa_render.html_dateiname({}) == "openapi.html"
    assert oa_render.html_dateiname({"info": "kein objekt"}) == "openapi.html"


def test_feste_basisadresse_wird_nach_dem_start_der_oberflaeche_gesetzt():
    """Ohne sie dreht sich beim Aufklappen einer Operation im `data:`-Rahmen ein endloser Ladekreis (im Browser nachgestellt, mit
    echten Dateien). Dieser Test sichert nur, dass der Aufruf in der Seite steht; das Verhalten prüft allein der Browser."""
    seite = oa_render.html_seite({"openapi": "3.0.3", "info": {"title": "T", "version": "1"}, "paths": {}})
    assert oa_render.BASIS_ADRESSE.startswith("https://") and ".invalid/" in oa_render.BASIS_ADRESSE  # reserviert, nie aufgelöst
    nach_start = seite[seite.index("SwaggerUIBundle(konfig)"):]
    assert f'window.ui.specActions.updateUrl("{oa_render.BASIS_ADRESSE}")' in nach_start
    assert "url" not in json.loads(re.search(r"var konfig = (.*);\n", seite).group(1))  # `url` in der Konfiguration würde `spec` verdrängen


def test_die_feste_basisadresse_wird_nicht_als_link_unter_dem_titel_gezeigt():
    seite = oa_render.html_seite({"openapi": "3.0.3", "info": {"title": "T", "version": "1"}, "paths": {}})
    assert ".swagger-ui .info a.link { display: none; }" in seite


def test_typ_tiefe_standard_ist_3_und_gilt_fuer_schema_liste_und_schema_ansicht():
    k = _konfig(oa_render.html_seite(SPEC))
    assert oa_render.TYP_TIEFE_STANDARD == 3
    assert k["defaultModelsExpandDepth"] == k["defaultModelExpandDepth"] == 3


@pytest.mark.parametrize("tiefe", range(oa_render.TYP_TIEFE_MIN, oa_render.TYP_TIEFE_MAX + 1))
def test_typ_tiefe_kommt_an(tiefe):
    k = _konfig(oa_render.html_seite(SPEC, typ_tiefe=tiefe))
    assert k["defaultModelsExpandDepth"] == tiefe and k["defaultModelExpandDepth"] == tiefe


@pytest.mark.parametrize("falsch", [0, oa_render.TYP_TIEFE_MAX + 1, -1, True, 2.5, "3", None])
def test_ungueltige_typ_tiefe_wird_abgelehnt(falsch):
    with pytest.raises(ValueError, match="typ_tiefe"):
        oa_render.html_seite(SPEC, typ_tiefe=falsch)
