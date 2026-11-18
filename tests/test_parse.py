"""Lesen, Prüfen und Zusammenfassen. Die Erwartungswerte der Beispiele sind von Hand aus den Dateien gezählt."""
import json
from pathlib import Path

import pytest

import oa_parse

BEISPIELE = Path(__file__).resolve().parent / "fixtures"


def _lies(name: str) -> oa_parse.Ergebnis:
    return oa_parse.lesen((BEISPIELE / name).read_text(encoding="utf-8"))


def _texte(erg: oa_parse.Ergebnis, stufe: str) -> list[str]:
    return [f"{b.ort} {b.text}" for b in erg.befunde if b.stufe == stufe]


# ---------------------------------------------------------------- Beispiele


def test_sendungen_ist_sauber_und_hat_die_gezaehlten_kennzahlen():
    erg = _lies("sendungen-3.0.yaml")
    assert erg.lesbar and erg.befunde == []
    kz = oa_parse.kennzahlen(erg.spec)
    # 5 Operationen: GET+POST /sendungen, GET+DELETE /sendungen/{id}, GET /touren/{id}/stopps
    assert (kz["operationen"], kz["pfade"], kz["tags"], kz["veraltet"]) == (5, 3, 2, 1)
    # Schemas: Status, Adresse, NeueSendung, Sendung, Stopp, Fehler
    assert kz["schemas"] == 6
    assert kz["version"] == "3.0.3" and kz["titel"] == "Sendungsverfolgung"


def test_lagerbestand_3_1_webhooks_zaehlen_nicht_als_operationen():
    erg = _lies("lagerbestand-3.1.yaml")
    assert erg.lesbar and erg.befunde == []
    kz = oa_parse.kennzahlen(erg.spec)
    assert (kz["version"], kz["operationen"], kz["pfade"], kz["schemas"]) == ("3.1.0", 2, 1, 1)


def test_fahrzeuge_2_0_nutzt_definitions_statt_components():
    erg = _lies("fahrzeuge-2.0.yaml")
    assert erg.lesbar and erg.befunde == []
    assert oa_parse.ist_v2(erg.spec)
    kz = oa_parse.kennzahlen(erg.spec)
    assert (kz["version"], kz["operationen"], kz["schemas"]) == ("2.0", 2, 1)


def test_mit_fehlern_findet_genau_die_eingebauten_fehler():
    erg = _lies("mit-fehlern.yaml")
    assert not erg.lesbar and erg.spec is not None
    fehler, warnungen = _texte(erg, oa_parse.FEHLER), _texte(erg, oa_parse.WARNUNG)
    assert len(fehler) == 2
    assert any("info.version" in t for t in fehler)
    assert any("Kundenliste" in t and "zeigt auf nichts" in t for t in fehler)
    # doppelter Schlüssel, 2 Pfadparameter, 1 Operation ohne responses, 1 doppelte operationId, 1 Pfad ohne "/", 1 fremde Datei
    assert len(warnungen) == 7
    assert sum("Pfadparameter" in t for t in warnungen) == 2
    assert sum("kommt doppelt vor" in t for t in warnungen) == 1
    assert sum("keine `responses`" in t for t in warnungen) == 1
    assert sum("gibt es schon" in t for t in warnungen) == 1
    assert sum("mit `/` beginnen" in t for t in warnungen) == 1
    assert sum("gemeinsam.yaml" in t for t in warnungen) == 1


def test_doppelter_schluessel_meldet_die_zeile():
    erg = _lies("mit-fehlern.yaml")
    zeilen = (BEISPIELE / "mit-fehlern.yaml").read_text(encoding="utf-8").splitlines()
    zeile = next(int(b.ort.split()[1]) for b in erg.befunde if "doppelt" in b.text)
    assert zeilen[zeile - 1].strip() == "name:"
    # Es ist die zweite der beiden Zeilen `name:`.
    assert zeile == [i + 1 for i, z in enumerate(zeilen) if z.strip() == "name:"][1]


@pytest.mark.parametrize("name", sorted(p.name for p in BEISPIELE.glob("*.yaml")))
def test_json_und_yaml_sind_gleich_gelesen(name):
    """Unabhängige Gegenprobe: das als JSON ausgegebene Ergebnis ergibt, mit der Standardbibliothek gelesen, dieselbe Spezifikation."""
    erg = _lies(name)
    als_json = json.dumps(erg.spec, ensure_ascii=False)
    assert oa_parse.lesen(als_json).spec == json.loads(als_json) == erg.spec


# ---------------------------------------------------------------- YAML-Eigenheiten


def test_no_off_on_yes_bleiben_text_nur_true_false_sind_wahrheitswerte():
    erg = oa_parse.lesen("openapi: 3.0.3\ninfo: {title: t, version: '1'}\npaths: {}\nx-land: no\nx-schalter: off\nx-on: on\nx-ja: yes\nx-w: true\nx-f: false\n")
    s = erg.spec
    assert (s["x-land"], s["x-schalter"], s["x-on"], s["x-ja"]) == ("no", "off", "on", "yes")
    assert s["x-w"] is True and s["x-f"] is False


def test_datum_bleibt_text():
    erg = oa_parse.lesen("openapi: 3.0.3\ninfo: {title: t, version: '1'}\npaths: {}\nx-datum: 2024-05-01\nx-zeit: 2024-05-01T08:30:00Z\n")
    assert erg.spec["x-datum"] == "2024-05-01"
    assert erg.spec["x-zeit"] == "2024-05-01T08:30:00Z"


def test_zahlen_als_antwortcodes_werden_textschluessel():
    erg = oa_parse.lesen(
        "openapi: 3.0.3\ninfo: {title: t, version: '1'}\npaths:\n  /a:\n    get:\n      responses:\n        200: {description: ok}\n        404: {description: weg}\n"
    )
    assert list(erg.spec["paths"]["/a"]["get"]["responses"]) == ["200", "404"]
    assert erg.lesbar


def test_anker_und_merge_schluessel_werden_aufgeloest():
    erg = oa_parse.lesen(
        "openapi: 3.0.3\ninfo: {title: t, version: '1'}\npaths: {}\nx-basis: &b {a: 1}\nx-kind:\n  <<: *b\n  c: 2\n"
    )
    assert erg.spec["x-kind"] == {"a": 1, "c": 2}


def test_json_eingabe_geht_auch():
    erg = oa_parse.lesen('{"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": {}}')
    assert erg.lesbar and erg.befunde == []


# ---------------------------------------------------------------- Lesefehler


def test_yaml_syntaxfehler_nennt_zeile_und_spalte():
    erg = oa_parse.lesen("openapi: 3.0.3\ninfo: [offen\npaths: {}\n")
    assert erg.spec is None and not erg.lesbar
    (b,) = erg.befunde
    assert b.stufe == oa_parse.FEHLER and b.ort.startswith("Zeile ")
    assert int(b.ort.split()[1].rstrip(",")) >= 2


@pytest.mark.parametrize("text", ["", "   \n\n"])
def test_leere_eingabe(text):
    erg = oa_parse.lesen(text)
    assert erg.spec is None and "leer" in erg.befunde[0].text


@pytest.mark.parametrize("text", ["- a\n- b\n", "nur text", "42"])
def test_oberste_ebene_muss_objekt_sein(text):
    erg = oa_parse.lesen(text)
    assert erg.spec is None and "Objekt" in erg.befunde[0].text


def test_zu_grosse_eingabe_wird_abgelehnt_ohne_zu_lesen():
    erg = oa_parse.lesen("a: " + "x" * oa_parse.MAX_EINGABE_ZEICHEN)
    assert erg.spec is None and "erlaubt sind höchstens" in erg.befunde[0].text


def test_alias_bombe_wird_abgebrochen():
    zeilen = ["openapi: 3.0.3", "info: {title: t, version: '1'}", "paths: {}", "x-l0: &l0 [a, a, a, a, a, a, a, a, a, a]"]
    for i in range(1, 9):
        zeilen.append(f"x-l{i}: &l{i} [" + ", ".join([f"*l{i - 1}"] * 10) + "]")
    erg = oa_parse.lesen("\n".join(zeilen))
    assert erg.spec is None
    assert "Anker" in erg.befunde[0].text


def test_zyklischer_alias_wird_gemeldet_statt_abzustuerzen():
    erg = oa_parse.lesen("openapi: 3.0.3\ninfo: {title: t, version: '1'}\npaths: {}\nx-z: &z [*z]\n")
    assert erg.spec is None and erg.fehler


# ---------------------------------------------------------------- Prüfung


def _mit(rest: str, kopf: str = "openapi: 3.0.3\ninfo: {title: t, version: '1'}\n") -> oa_parse.Ergebnis:
    return oa_parse.lesen(kopf + rest)


def test_fehlende_version_und_nicht_unterstuetzte_version():
    assert any("openapi" in b.text for b in oa_parse.lesen("info: {title: t, version: '1'}\npaths: {}\n").fehler)
    erg = oa_parse.lesen("openapi: 4.0.0\ninfo: {title: t, version: '1'}\npaths: {}\n")
    assert any("nicht unterstützt" in b.text for b in erg.fehler)


def test_paths_fehlt_ist_fehler_ausser_3_1_mit_webhooks_oder_components():
    assert any(b.ort == "paths" for b in _mit("").fehler)
    ok =_mit("webhooks:\n  w:\n    post: {responses: {'200': {description: ok}}}\n", "openapi: 3.1.0\ninfo: {title: t, version: '1'}\n")
    assert ok.lesbar and ok.befunde == []
    nur_3_0 = _mit("webhooks:\n  w: {}\n")
    assert any(b.ort == "paths" for b in nur_3_0.fehler)


def test_pfadparameter_ueber_gemeinsame_und_ref_parameter_gelten_als_beschrieben():
    erg = _mit(
        "paths:\n  /a/{x}/{y}:\n    parameters:\n      - {name: x, in: path, required: true, schema: {type: string}}\n"
        "      - $ref: '#/components/parameters/Y'\n    get:\n      responses: {'200': {description: ok}}\n"
        "components:\n  parameters:\n    Y: {name: y, in: path, required: true, schema: {type: string}}\n"
    )
    assert erg.befunde == []


def test_pfadparameter_nur_im_query_gilt_nicht():
    erg = _mit("paths:\n  /a/{x}:\n    get:\n      parameters:\n        - {name: x, in: query, schema: {type: string}}\n      responses: {'200': {description: ok}}\n")
    assert [b.stufe for b in erg.befunde] == [oa_parse.WARNUNG]


def test_ref_mit_escape_und_listenindex_wird_aufgeloest():
    spec = {"paths": {"/a": {"x": [{"k": 1}]}}}
    assert oa_parse._aufloesen(spec, "#/paths/~1a/x/0/k") == 1
    assert oa_parse._aufloesen(spec, "#/paths/~1b") is None
    assert oa_parse._aufloesen(spec, "#/paths/~1a/x/5") is None
    assert oa_parse._aufloesen(spec, "#") == spec


def test_kaputte_ref_wird_in_tiefer_verschachtelung_gefunden_ohne_rekursionsfehler():
    tief: dict = {"$ref": "#/nichts"}
    for _ in range(3000):
        tief = {"k": tief}
    refs = list(oa_parse._alle_refs(tief))
    assert refs == [("#/nichts", ".".join(["k"] * 3000))]


def test_operationen_ohne_summary_und_tags_haben_leere_felder():
    erg = _mit("paths:\n  /a:\n    get:\n      responses: {'200': {description: ok}}\n")
    (op,) = oa_parse.operationen(erg.spec)
    assert (op.methode, op.pfad, op.zusammenfassung, op.tags, op.veraltet, op.operation_id) == ("GET", "/a", "", [], False, "")
    assert oa_parse.kennzahlen(erg.spec)["tags"] == 0


# ---------------------------------------------------------------- Hochgeladene Bytes


def test_aus_bytes_liest_utf8_und_entfernt_die_bom_markierung():
    assert oa_parse.aus_bytes("titel: Größe\n".encode("utf-8")) == ("titel: Größe\n", "")
    assert oa_parse.aus_bytes(b"\xef\xbb\xbfa: 1") == ("a: 1", "")


def test_aus_bytes_meldet_falsche_kodierung_und_zu_grosse_dateien():
    text, fehler = oa_parse.aus_bytes("Größe".encode("latin-1"))
    assert text == "" and "UTF-8" in fehler
    text, fehler = oa_parse.aus_bytes(b"x" * (oa_parse.MAX_EINGABE_ZEICHEN * 4 + 1))
    assert text == "" and "zu groß" in fehler
