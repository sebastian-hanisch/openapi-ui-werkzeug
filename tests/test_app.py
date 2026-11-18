"""AppTest-Rauchtests des Werkzeugs (nur Upload). Die Oberfläche selbst (Swagger UI im Rahmen) prüft nur der Browser."""
import base64
import json
import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SENDUNGEN = FIXTURES / "sendungen-3.0.yaml"
LAGER = FIXTURES / "lagerbestand-3.1.yaml"
FEHLERHAFT = FIXTURES / "mit-fehlern.yaml"
MIME = "application/x-yaml"


def _app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def _hochladen(at: AppTest, *pfade: Path) -> AppTest:
    at.file_uploader(key="dateien").set_value([(p.name, p.read_bytes(), MIME) for p in pfade]).run()
    assert not at.exception
    return at


def _metriken(at: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in at.metric}


def _rahmen(at: AppTest) -> list:
    return at.get("iframe")


def _konfig_im_rahmen(at: AppTest) -> dict:
    url = _rahmen(at)[0].proto.src
    seite = base64.b64decode(url.split(",", 1)[1]).decode("utf-8")
    return json.loads(re.search(r"var konfig = (.*);\n", seite).group(1))


def test_ohne_datei_nur_hinweis_keine_oberflaeche_keine_beispiele():
    at = _app()
    assert len(at.info) == 1 and "hoch" in at.info[0].value
    assert _rahmen(at) == [] and not at.metric
    assert at.get("file_uploader") and len(at.radio) == 0 and len(at.text_area) == 0
    assert [s.key for s in at.selectbox] == ["doc_expansion"]  # keine Beispielauswahl


def test_hochgeladene_datei_wird_gelesen_und_gezeichnet():
    at = _hochladen(_app(), SENDUNGEN)
    assert not at.error
    assert _metriken(at) == {"Version": "3.0.3", "Operationen": "5", "Pfade": "3", "Gruppen (Tags)": "2", "Schemas": "6"}
    assert len(_rahmen(at)) == 1
    assert _konfig_im_rahmen(at)["spec"]["info"]["title"] == "Sendungsverfolgung"


def test_json_datei_geht_auch():
    daten = json.dumps({"openapi": "3.0.3", "info": {"title": "J", "version": "1"}, "paths": {"/a": {"get": {"responses": {"200": {"description": "ok"}}}}}})
    at = _app()
    at.file_uploader(key="dateien").set_value([("j.json", daten.encode("utf-8"), "application/json")]).run()
    assert not at.exception and not at.error
    assert _metriken(at)["Operationen"] == "1"


def test_mehrere_dateien_mit_auswahl_und_wechsel():
    at = _hochladen(_app(), SENDUNGEN, LAGER)
    assert [s.key for s in at.selectbox] == ["gewaehlt", "doc_expansion"]
    assert _metriken(at)["Version"] == "3.0.3"
    at.selectbox(key="gewaehlt").set_value(1).run()
    assert not at.exception
    assert (_metriken(at)["Version"], _metriken(at)["Operationen"]) == ("3.1.0", "2")
    assert _konfig_im_rahmen(at)["spec"]["info"]["title"] == "Lagerbestand"


def test_zwei_gleich_benannte_dateien_sind_unterscheidbar():
    at = _hochladen(_app(), SENDUNGEN, SENDUNGEN)
    gewaehlt = at.selectbox(key="gewaehlt")
    assert gewaehlt.options == ["1. sendungen-3.0.yaml (3 Pfade)", "2. sendungen-3.0.yaml (3 Pfade)"]


def test_fehlerhafte_datei_zeigt_fehler_und_zeichnet_trotzdem():
    at = _hochladen(_app(), FEHLERHAFT)
    assert len(at.error) == 1 and "mit-fehlern.yaml: 3 Fehler" in at.error[0].value
    assert len(_rahmen(at)) == 1
    pruefung = next(e for e in at.expander if e.label.startswith("🔎 Prüfung"))
    # 2 Fehler in der Datei selbst + 1 für den `$ref` auf „gemeinsam.yaml“, die nicht hochgeladen wurde (die Demo-Variante warnt dort nur)
    assert pruefung.label == "🔎 Prüfung: 3 Fehler, 6 Warnungen"
    meldungen = list(at.dataframe[0].value["Meldung"])
    assert any("gemeinsam.yaml" in m and "nicht hochgeladen" in m for m in meldungen)


def test_unlesbares_yaml_zeigt_fehlertabelle_ohne_rahmen():
    at = _app()
    at.file_uploader(key="dateien").set_value([("kaputt.yaml", b"openapi: 3.0.3\ninfo: [offen\n", MIME)]).run()
    assert not at.exception
    assert len(at.error) == 1 and "Eine Oberfläche ist so nicht möglich" in at.error[0].value
    assert _rahmen(at) == [] and not at.metric
    assert len(at.dataframe) == 1


def test_falsche_kodierung_wird_gemeldet():
    at = _app()
    at.file_uploader(key="dateien").set_value([("alt.yaml", "titel: Größe".encode("latin-1"), MIME)]).run()
    assert not at.exception
    assert len(at.error) == 1 and "alt.yaml: 1 Fehler" in at.error[0].value
    assert any("UTF-8" in m for m in at.dataframe[0].value["Meldung"])
    assert _rahmen(at) == []


def test_leere_datei_wird_als_leer_gemeldet():
    at = _app()
    at.file_uploader(key="dateien").set_value([("leer.yaml", b"", MIME)]).run()
    assert not at.exception and len(at.error) == 1
    assert _rahmen(at) == []


ORDNER = FIXTURES / "ordner"


def _ordner_zip(name: str = "paketdienst.zip") -> tuple[str, bytes, str]:
    import io
    import zipfile

    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as zf:
        for p in sorted(ORDNER.rglob("*.yaml")):
            zf.write(p, "paketdienst/" + p.relative_to(ORDNER).as_posix())
    return name, puffer.getvalue(), "application/zip"


def test_ordner_als_zip_wird_gebuendelt_und_gezeichnet():
    at = _app()
    at.file_uploader(key="dateien").set_value([_ordner_zip()]).run()
    assert not at.exception and not at.error
    assert _metriken(at) == {"Version": "3.0.3", "Operationen": "3", "Pfade": "2", "Gruppen (Tags)": "2", "Schemas": "3"}
    assert [s.key for s in at.selectbox] == ["doc_expansion"]  # nur eine Einstiegsdatei: keine Auswahl
    spec = _konfig_im_rahmen(at)["spec"]
    assert not any(r.startswith(".") for r, _ in _refs(spec))  # keine Verweise auf Dateien mehr im gezeichneten Dokument
    uebersicht = next(e for e in at.expander if e.label.startswith("📁 Dateien"))
    assert uebersicht.label == "📁 Dateien: 6 zu einer Spezifikation gebündelt"


def test_ordner_einzeln_hochgeladen_gibt_dasselbe():
    at = _app()
    at.file_uploader(key="dateien").set_value([(p.name, p.read_bytes(), MIME) for p in sorted(ORDNER.rglob("*.yaml"))]).run()
    assert not at.exception and not at.error
    assert _metriken(at)["Operationen"] == "3" and _metriken(at)["Schemas"] == "3"


def test_fehlt_eine_datei_des_ordners_steht_es_in_der_pruefung_und_die_oberflaeche_kommt_trotzdem():
    at = _app()
    dateien = [(p.name, p.read_bytes(), MIME) for p in sorted(ORDNER.rglob("*.yaml")) if p.name != "Adresse.yaml"]
    at.file_uploader(key="dateien").set_value(dateien).run()
    assert not at.exception
    assert len(at.error) == 1 and "Fehler" in at.error[0].value and len(_rahmen(at)) == 1
    assert any("Adresse.yaml" in m and "nicht hochgeladen" in m for m in at.dataframe[0].value["Meldung"])


def test_unbenutzte_dateien_stehen_in_der_uebersicht():
    at = _hochladen(_app(), SENDUNGEN)  # eine einzelne Datei ohne Verweise: keine Dateiübersicht
    assert not [e for e in at.expander if e.label.startswith("📁")]
    at = _app()
    at.file_uploader(key="dateien").set_value(
        [("w.yaml", (ORDNER / "openapi.yaml").read_bytes(), MIME), ("lose.yaml", b"type: string\n", MIME)]
    ).run()
    assert not at.exception
    assert any(e.label.endswith("1 nicht verwendet") for e in at.expander if e.label.startswith("📁"))


def test_zip_mit_bausteindatei_vor_der_beschreibung_zeigt_zuerst_die_beschreibung():
    """Form eines echten Ordners: `common/…` (openapi-Kopf, aber `paths: {}`) steht alphabetisch vor `services/…`."""
    import io
    import zipfile

    kopf = "openapi: 3.0.3\ninfo: {title: %s, version: '1'}\n"
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as zf:
        zf.writestr("api/", "")
        zf.writestr("api/common/bausteine.yml", kopf % "Bausteine" + "paths: {}\ncomponents:\n  schemas:\n    S: {type: string}\n")
        zf.writestr(
            "api/services/dienst/openapi.yml",
            kopf % "Dienst" + "paths:\n  /a:\n    $ref: ./paths/a.yml\n  /b:\n    $ref: ./paths/a.yml\n",
        )
        zf.writestr(
            "api/services/dienst/paths/a.yml",
            "get:\n  responses:\n    '200':\n      description: ok\n      content:\n        application/json:\n          schema:\n"
            "            $ref: ../../../common/bausteine.yml#/components/schemas/S\n",
        )
    at = _app()
    at.file_uploader(key="dateien").set_value([("api.zip", puffer.getvalue(), "application/zip")]).run()
    assert not at.exception and not at.error
    # die Bausteindatei ist ausgeblendet: nur eine Beschreibung → keine Auswahl, aber ein Schalter mit der Zahl der ausgeblendeten
    assert [s.key for s in at.selectbox] == ["doc_expansion"]
    schalter = at.checkbox(key="bausteine_zeigen")
    assert schalter.label == "Auch Dateien ohne Pfade anbieten (1 ausgeblendet)" and schalter.value is False
    assert _metriken(at)["Operationen"] == "2" and _konfig_im_rahmen(at)["spec"]["info"]["title"] == "Dienst"
    schalter.set_value(True).run()
    gewaehlt = at.selectbox(key="gewaehlt")
    assert gewaehlt.options == [
        "1. api.zip: api/services/dienst/openapi.yml (2 Pfade, bindet 2 Dateien ein)",
        "2. api.zip: api/common/bausteine.yml (nur Bausteine, keine Pfade)",
    ]
    gewaehlt.set_value(1).run()
    assert not at.exception and _metriken(at)["Operationen"] == "0"
    at.checkbox(key="bausteine_zeigen").set_value(False).run()  # Liste wird wieder kürzer, der gemerkte Platz 1 gibt es nicht mehr
    assert not at.exception and _metriken(at)["Operationen"] == "2"


def test_nur_bausteine_hochgeladen_bleiben_sichtbar_ohne_schalter():
    at = _app()
    at.file_uploader(key="dateien").set_value(
        [("b.yml", b"openapi: 3.0.3\ninfo: {title: B, version: '1'}\npaths: {}\ncomponents:\n  schemas:\n    S: {type: string}\n", MIME)]
    ).run()
    assert not at.exception and not at.error and len(_rahmen(at)) == 1
    assert [c.key for c in at.checkbox] == ["filter_leiste", "try_it_out"]  # kein Schalter: nichts ist ausgeblendet


def _refs(spec):
    import oa_parse

    return list(oa_parse._alle_refs(spec))


def test_try_it_out_schaltet_das_senden_in_der_oberflaeche():
    at = _hochladen(_app(), SENDUNGEN)
    assert _konfig_im_rahmen(at)["supportedSubmitMethods"] == []
    at.checkbox(key="try_it_out").set_value(True).run()
    assert not at.exception
    assert "post" in _konfig_im_rahmen(at)["supportedSubmitMethods"]


@pytest.mark.parametrize("hoehe", [400, 2000])
def test_hoehe_am_rand_laeuft(hoehe):
    at = _hochladen(_app(), SENDUNGEN)
    at.slider(key="hoehe").set_value(hoehe).run()
    assert not at.exception and len(_rahmen(at)) == 1


@pytest.mark.parametrize("schluessel,wert", [("doc_expansion", "full"), ("doc_expansion", "none"), ("filter_leiste", False)])
def test_darstellungsschalter_kommen_in_der_oberflaeche_an(schluessel, wert):
    at = _hochladen(_app(), SENDUNGEN)
    if isinstance(wert, bool):
        at.checkbox(key=schluessel).set_value(wert).run()
    else:
        at.selectbox(key=schluessel).set_value(wert).run()
    assert not at.exception
    konfig = _konfig_im_rahmen(at)
    assert konfig["docExpansion"] == (wert if schluessel == "doc_expansion" else "list")
    assert konfig["filter"] is (wert if schluessel == "filter_leiste" else True)


def test_typ_tiefe_ist_standardmaessig_3_und_der_regler_kommt_in_der_oberflaeche_an():
    at = _hochladen(_app(), SENDUNGEN)
    assert at.slider(key="typ_tiefe").value == 3
    assert _konfig_im_rahmen(at)["defaultModelExpandDepth"] == 3
    at.slider(key="typ_tiefe").set_value(5).run()
    assert not at.exception
    konfig = _konfig_im_rahmen(at)
    assert konfig["defaultModelExpandDepth"] == 5 and konfig["defaultModelsExpandDepth"] == 5
