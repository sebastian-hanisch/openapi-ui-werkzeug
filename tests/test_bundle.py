"""Mehrere Dateien bündeln. Erwartungswerte des Ordnerbeispiels sind von Hand aus den Dateien gezählt."""
import io
import json
import zipfile
from pathlib import Path

import pytest

import oa_bundle
import oa_parse

ORDNER = Path(__file__).resolve().parent / "fixtures" / "ordner"
WURZEL_ZIP = "paketdienst/openapi.yaml"


def _ordner_dateien() -> dict[str, bytes]:
    return {p.relative_to(ORDNER).as_posix(): p.read_bytes() for p in sorted(ORDNER.rglob("*.yaml"))}


def _zip(dateien: dict[str, bytes | str], name: str = "api.zip") -> tuple[str, bytes]:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as zf:
        for pfad, inhalt in dateien.items():
            zf.writestr(pfad, inhalt)
    return name, puffer.getvalue()


def _alle(dateien: dict[str, str]) -> list[tuple[str, bytes]]:
    """Dateien einzeln hochgeladen (nur Dateiname, keine Ordner)."""
    return [(pfad.rsplit("/", 1)[-1], text.encode("utf-8")) for pfad, text in dateien.items()]


def _buendeln(uploads, wurzel: str | None = None) -> oa_bundle.Buendel:
    satz = oa_bundle.laden(uploads)
    return oa_bundle.buendeln(satz, wurzel or satz.kandidaten()[0].pfad)


def _texte(b: oa_bundle.Buendel, stufe: str) -> list[str]:
    return [f"{x.ort} | {x.text}" for x in b.ergebnis.befunde if x.stufe == stufe]


def _bleibt_kein_dateiverweis(spec: dict) -> None:
    for ref, ort in oa_parse._alle_refs(spec):
        assert ref.startswith("#"), (ref, ort)
        assert oa_parse._aufloesen(spec, ref) is not None, (ref, ort)


WURZEL_MIN = """openapi: 3.0.3
info: {title: T, version: "1"}
paths:
  /a:
    get:
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                $ref: ./%s
"""


# ---------------------------------------------------------------- Ordnerbeispiel


def test_zip_des_ordners_ergibt_eine_saubere_spezifikation():
    zipname = _zip({f"paketdienst/{p}": d for p, d in _ordner_dateien().items()})
    satz = oa_bundle.laden([zipname])
    assert [d.pfad for d in satz.kandidaten()] == [WURZEL_ZIP]
    b = oa_bundle.buendeln(satz, WURZEL_ZIP)
    assert b.ergebnis.lesbar and b.ergebnis.befunde == []
    kz = oa_parse.kennzahlen(b.ergebnis.spec)
    # GET+POST /sendungen und GET /sendungen/{id}; Schemas Fehler, Adresse, Sendung; Tags Sendungen, Zustellung
    assert (kz["operationen"], kz["pfade"], kz["tags"], kz["schemas"]) == (3, 2, 2, 3)
    assert len(b.verwendet) == 6 and b.unbenutzt == []
    _bleibt_kein_dateiverweis(b.ergebnis.spec)


def test_einzeln_hochgeladene_dateien_geben_dieselbe_spezifikation_wie_das_zip():
    aus_zip = _buendeln([_zip({f"paketdienst/{p}": d for p, d in _ordner_dateien().items()})])
    einzeln = _buendeln([(p.rsplit("/", 1)[-1], d) for p, d in _ordner_dateien().items()])
    assert einzeln.ergebnis.befunde == []
    assert einzeln.ergebnis.spec == aus_zip.ergebnis.spec


def test_schemas_parameter_und_antworten_behalten_ihre_namen_in_components():
    spec = _buendeln([_zip({f"x/{p}": d for p, d in _ordner_dateien().items()})]).ergebnis.spec
    comp = spec["components"]
    assert set(comp["schemas"]) == {"Fehler", "Adresse", "Sendung"}  # kein „Adresse_2“: der Name der Wurzel bleibt
    assert set(comp["parameters"]) == {"Limit"} and set(comp["responses"]) == {"NichtAngemeldet"}
    assert "securitySchemes" in comp  # die Wurzel behält ihre eigenen Abschnitte
    assert spec["paths"]["/sendungen"]["get"]["parameters"] == [{"$ref": "#/components/parameters/Limit"}]
    # der Verweis auf eine Antwort in einer fremden Datei bleibt ein Verweis, den die Oberfläche versteht
    assert spec["paths"]["/sendungen"]["get"]["responses"]["401"] == {"$ref": "#/components/responses/NichtAngemeldet"}


def test_rekursives_schema_wird_ein_verweis_auf_sich_selbst():
    spec = _buendeln([_zip({f"x/{p}": d for p, d in _ordner_dateien().items()})]).ergebnis.spec
    sendung = spec["components"]["schemas"]["Sendung"]
    assert sendung["properties"]["teilsendungen"]["items"] == {"$ref": "#/components/schemas/Sendung"}
    assert sendung["properties"]["empfaenger"] == {"$ref": "#/components/schemas/Adresse"}
    json.dumps(spec)  # keine Zyklen im Objekt, die Seite lässt sich schreiben


def test_pfadeintrag_aus_eigener_datei_wird_eingesetzt():
    spec = _buendeln([_zip({f"x/{p}": d for p, d in _ordner_dateien().items()})]).ergebnis.spec
    item = spec["paths"]["/sendungen/{id}"]
    assert "$ref" not in item and item["get"]["operationId"] == "sendungAbrufen" and item["parameters"][0]["name"] == "id"


def test_beispielwert_mit_dollar_ref_wird_nicht_als_verweis_gelesen():
    schema = "type: object\nexample:\n  $ref: ./gibt-es-nicht.yaml\n"
    b = _buendeln(_alle({"w.yaml": WURZEL_MIN % "s.yaml", "s.yaml": schema}))
    assert b.ergebnis.befunde == []
    assert b.ergebnis.spec["components"]["schemas"]["s"]["example"] == {"$ref": "./gibt-es-nicht.yaml"}


# ---------------------------------------------------------------- Fehlerfälle


def test_fehlende_datei_ist_ein_fehler_und_der_verweis_bleibt():
    b = _buendeln(_alle({"w.yaml": WURZEL_MIN % "fehlt.yaml"}))
    assert b.ergebnis.spec is not None
    fehler = _texte(b, oa_parse.FEHLER)
    assert len(fehler) == 1 and "fehlt.yaml" in fehler[0] and "nicht hochgeladen" in fehler[0]


def test_dieselbe_fehlende_datei_wird_nur_einmal_gemeldet():
    text = WURZEL_MIN % "fehlt.yaml" + "  /b:\n    get:\n      responses:\n        '200':\n          description: ok\n          content:\n            application/json:\n              schema:\n                $ref: ./fehlt.yaml\n"
    assert len(_texte(_buendeln(_alle({"w.yaml": text})), oa_parse.FEHLER)) == 1


def test_nicht_lesbare_verwiesene_datei_ist_ein_fehler_mit_grund():
    b = _buendeln([("w.yaml", (WURZEL_MIN % "kaputt.yaml").encode()), ("kaputt.yaml", b"a: [offen\n")])
    fehler = _texte(b, oa_parse.FEHLER)
    assert any("kaputt.yaml" in f and "nicht lesbar" in f for f in fehler)


def test_verweis_auf_nichts_in_der_fremden_datei():
    b = _buendeln(_alle({"w.yaml": WURZEL_MIN % "s.yaml#/components/schemas/Nope", "s.yaml": "components: {schemas: {A: {type: string}}}\n"}))
    assert any("zeigt auf nichts" in f for f in _texte(b, oa_parse.FEHLER))


def test_gleicher_dateiname_in_zwei_ordnern_ist_nicht_eindeutig_ohne_ordnerstruktur():
    uploads = [("w.yaml", (WURZEL_MIN % "x.yaml").encode()), _zip({"a/x.yaml": "type: string\n", "b/x.yaml": "type: integer\n"})]
    b = _buendeln(uploads, "w.yaml")
    fehler = _texte(b, oa_parse.FEHLER)
    assert len(fehler) == 1 and "nicht eindeutig" in fehler[0] and "ZIP" in fehler[0]


def test_ordnerstruktur_im_zip_loest_gleiche_dateinamen_auf():
    wurzel = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths: {}\ncomponents:\n  schemas:\n    A: {$ref: ./a/x.yaml}\n    B: {$ref: ./b/x.yaml}\n"
    b = _buendeln([_zip({"openapi.yaml": wurzel, "a/x.yaml": "type: string\n", "b/x.yaml": "type: integer\n"})])
    assert b.ergebnis.befunde == []
    assert b.ergebnis.spec["components"]["schemas"] == {"A": {"type": "string"}, "B": {"type": "integer"}}


def test_netzadresse_wird_nicht_geladen_nur_gewarnt():
    b = _buendeln(_alle({"w.yaml": WURZEL_MIN % "x.yaml"}) + [("x.yaml", b"type: object\nproperties:\n  a:\n    $ref: https://example.org/a.yaml\n")])
    warn = _texte(b, oa_parse.WARNUNG)
    assert len(warn) == 1 and "Netz" in warn[0] and "https://example.org/a.yaml" in warn[0]
    assert oa_parse.schemas(b.ergebnis.spec)["x"]["properties"]["a"] == {"$ref": "https://example.org/a.yaml"}


def test_verweis_im_kreis_ohne_benannte_stelle_endet_und_wird_als_schema_abgelegt():
    wurzel = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths: {}\nx-a:\n  $ref: ./a.yaml\n"
    b = _buendeln(_alle({"w.yaml": wurzel, "a.yaml": "n:\n  $ref: ./b.yaml\n", "b.yaml": "m:\n  $ref: ./a.yaml\n"}))
    spec = b.ergebnis.spec
    assert spec is not None and b.ergebnis.fehler == []
    # a → b → a: der erste Umlauf bleibt dort eingesetzt, der Kreis wird beim Wiedersehen von a aufgeschnitten
    assert spec["x-a"] == {"n": {"m": {"$ref": "#/components/schemas/a"}}}
    assert spec["components"]["schemas"]["a"] == {"n": {"$ref": "#/components/schemas/b"}}
    assert spec["components"]["schemas"]["b"] == {"m": {"$ref": "#/components/schemas/a"}}
    _bleibt_kein_dateiverweis(spec)
    json.dumps(spec)


def test_zwei_dateien_mit_gleich_benanntem_schema_bekommen_verschiedene_namen():
    w = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths: {}\ncomponents:\n  schemas:\n    X: {$ref: ./a.yaml#/components/schemas/Item}\n    Y: {$ref: ./b.yaml#/components/schemas/Item}\n"
    a = "components: {schemas: {Item: {type: string}}}\n"
    b_ = "components: {schemas: {Item: {type: integer}}}\n"
    spec = _buendeln([("w.yaml", w.encode()), _zip({"a.yaml": a, "b.yaml": b_})], "w.yaml").ergebnis.spec
    assert spec["components"]["schemas"] == {"X": {"type": "string"}, "Y": {"type": "integer"}}  # benannte Plätze der Wurzel, kein Item


def test_gleicher_name_aus_zwei_dateien_ohne_platz_in_der_wurzel_wird_durchnummeriert():
    w = WURZEL_MIN % "a.yaml#/components/schemas/Item" + "  /b:\n    get:\n      responses:\n        '200':\n          description: ok\n          content:\n            application/json:\n              schema:\n                $ref: ./b.yaml#/components/schemas/Item\n"
    uploads = [("w.yaml", w.encode()), ("a.yaml", b"components: {schemas: {Item: {type: string}}}\n"), ("b.yaml", b"components: {schemas: {Item: {type: integer}}}\n")]
    spec = _buendeln(uploads, "w.yaml").ergebnis.spec
    assert spec["components"]["schemas"] == {"Item": {"type": "string"}, "Item_2": {"type": "integer"}}


def test_geschwisterfelder_neben_dem_verweis_bleiben():
    w = WURZEL_MIN.replace("$ref: ./%s", "$ref: ./s.yaml\n                description: eigener Text") % ()
    spec = _buendeln(_alle({"w.yaml": w, "s.yaml": "type: string\n"})).ergebnis.spec
    schema = spec["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/s", "description": "eigener Text"}


def test_swagger_2_legt_nach_definitions_ab():
    w = (
        "swagger: '2.0'\ninfo: {title: T, version: '1'}\npaths:\n  /p:\n    get:\n      responses:\n        '200':\n          description: ok\n"
        "          schema:\n            $ref: ./defs.yaml#/definitions/Pet\n"
    )
    d = "definitions:\n  Pet:\n    type: object\n    properties:\n      freund:\n        $ref: '#/definitions/Pet'\n"
    b = _buendeln(_alle({"w.yaml": w, "defs.yaml": d}))
    assert b.ergebnis.befunde == []
    spec = b.ergebnis.spec
    assert spec["paths"]["/p"]["get"]["responses"]["200"]["schema"] == {"$ref": "#/definitions/Pet"}
    assert spec["definitions"]["Pet"]["properties"]["freund"] == {"$ref": "#/definitions/Pet"}


def test_verweis_aus_fremder_datei_zurueck_auf_die_wurzel():
    w = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths: {}\ncomponents:\n  schemas:\n    Basis: {type: string}\n    Kind: {$ref: ./k.yaml}\n"
    k = "type: object\nproperties:\n  b:\n    $ref: ./w.yaml#/components/schemas/Basis\n"
    spec = _buendeln(_alle({"w.yaml": w, "k.yaml": k}), "w.yaml").ergebnis.spec
    assert spec["components"]["schemas"]["Kind"]["properties"]["b"] == {"$ref": "#/components/schemas/Basis"}


def test_fragment_ohne_info_ist_kein_fehler_nur_die_wurzel_wird_geprueft():
    b = _buendeln(_alle({"w.yaml": WURZEL_MIN % "s.yaml", "s.yaml": "type: string\n"}))
    assert b.ergebnis.befunde == []


def test_dateien_ohne_verweis_sind_unbenutzt_und_eine_zweite_wurzel_ist_ein_zweiter_kandidat():
    w1 = "openapi: 3.0.3\ninfo: {title: Eins, version: '1'}\npaths: {}\n"
    w2 = "openapi: 3.0.3\ninfo: {title: Zwei, version: '1'}\npaths: {}\n"
    satz = oa_bundle.laden(_alle({"eins.yaml": w1, "zwei.yaml": w2, "lose.yaml": "type: string\n"}))
    assert [d.pfad for d in satz.kandidaten()] == ["eins.yaml", "zwei.yaml"]
    b = oa_bundle.buendeln(satz, "zwei.yaml")
    assert b.ergebnis.spec["info"]["title"] == "Zwei"
    assert b.verwendet == ["zwei.yaml"] and b.unbenutzt == ["eins.yaml", "lose.yaml"]


def test_beschreibungen_mit_pfaden_stehen_vor_bausteindateien_sonst_bleibt_die_reihenfolge():
    kopf = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\n"
    dateien = {
        "a-bausteine.yml": kopf + "paths: {}\n",
        "b-api.yml": kopf + "paths:\n  /x: {}\n",
        "c-bausteine.yml": kopf,
        "d-hooks.yml": "openapi: 3.1.0\ninfo: {title: T, version: '1'}\nwebhooks:\n  w: {}\n",
        "e-api.yml": kopf + "paths:\n  /y: {}\n  /z: {}\n",
    }
    satz = oa_bundle.laden(_alle(dateien))
    # erst mit Pfaden/Webhooks (mehr zuerst, bei Gleichstand die Reihenfolge des Hochladens), dann die reinen Bausteine
    assert [d.pfad for d in satz.kandidaten()] == ["e-api.yml", "b-api.yml", "d-hooks.yml", "a-bausteine.yml", "c-bausteine.yml"]
    assert [e.beschriftung for e in satz.einstiege()] == [
        "e-api.yml (2 Pfade)", "b-api.yml (1 Pfad)", "d-hooks.yml (1 Webhook)",
        "a-bausteine.yml (nur Bausteine, keine Pfade)", "c-bausteine.yml (nur Bausteine, keine Pfade)",
    ]


KOPF = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\n"


def _schema_ref(ziel: str) -> str:
    """Der Block `responses:` einer Operation (steht unter `get:` eines Pfades, der unter `paths:` steht: Einrückung 6)."""
    zeilen = [
        "responses:", "  '200':", "    description: ok", "    content:", "      application/json:", "        schema:", f"          $ref: {ziel}",
    ]
    return "".join(" " * 6 + z + "\n" for z in zeilen)


def test_beschreibung_die_eine_andere_einbindet_steht_vor_der_eingebundenen_auch_wenn_diese_pfade_hat():
    """`a.yml` hat mehr Pfade, wird aber von `b.yml` eingebunden: Baustein. `b.yml` ist der Einstieg."""
    dateien = {
        "a.yml": KOPF + "paths:\n  /1: {}\n  /2: {}\n  /3: {}\ncomponents:\n  schemas:\n    S: {type: string}\n",
        "b.yml": KOPF + "paths:\n  /x:\n    get:\n" + _schema_ref("./a.yml#/components/schemas/S"),
    }
    einstiege = oa_bundle.laden(_alle(dateien)).einstiege()
    assert [e.datei.pfad for e in einstiege] == ["b.yml", "a.yml"]
    assert [e.ist_freie_beschreibung for e in einstiege] == [True, False]
    assert [e.beschriftung for e in einstiege] == ["b.yml (1 Pfad, bindet 1 Datei ein)", "a.yml (3 Pfade, selbst eingebunden)"]


def test_mehr_pfade_dann_mehr_erreichte_dateien_entscheiden_zwischen_freien_beschreibungen():
    dateien = {
        "klein.yml": KOPF + "paths:\n  /k:\n    get:\n" + _schema_ref("./s1.yml"),
        "gross.yml": KOPF + "paths:\n  /g1:\n    get:\n" + _schema_ref("./s1.yml") + "  /g2:\n    get:\n" + _schema_ref("./s2.yml"),
        "gleich-a.yml": KOPF + "paths:\n  /a: {}\n",
        "gleich-b.yml": KOPF + "paths:\n  /b:\n    get:\n" + _schema_ref("./s2.yml") + "    post:\n" + _schema_ref("./s1.yml"),
        "s1.yml": "type: string\n",
        "s2.yml": "type: string\n",
        "bausteine.yml": KOPF + "paths: {}\n",
    }
    einstiege = oa_bundle.laden(_alle(dateien)).einstiege()
    # gross: 2 Pfade; danach je 1 Pfad: gleich-b erreicht 2 Dateien, klein 1, gleich-a keine; zuletzt der reine Baustein
    assert [e.datei.pfad for e in einstiege] == ["gross.yml", "gleich-b.yml", "klein.yml", "gleich-a.yml", "bausteine.yml"]
    assert [(e.pfade, e.erreicht) for e in einstiege[:4]] == [(2, 2), (1, 2), (1, 1), (1, 0)]


def test_erreichbarkeit_zaehlt_mittelbare_verweise_und_kreise_haengen_nicht():
    dateien = {
        "w.yml": KOPF + "paths:\n  /x:\n    get:\n" + _schema_ref("./a.yml"),
        "a.yml": "type: object\nproperties:\n  b:\n    $ref: ./b.yml\n",
        "b.yml": "type: object\nproperties:\n  a:\n    $ref: ./a.yml\n  w:\n    $ref: ./w.yml\n",
    }
    einstiege = oa_bundle.laden(_alle(dateien)).einstiege()
    assert [(e.datei.pfad, e.erreicht, e.eingebunden_von) for e in einstiege] == [("w.yml", 2, 1)]  # a, b: mittelbar über a; w selbst gezählt als eingebunden


def test_verweise_auf_netz_und_nicht_vorhandene_dateien_zaehlen_nicht():
    dateien = {"w.yml": KOPF + "paths:\n  /x:\n    get:\n" + _schema_ref("https://example.org/a.yml") + "  /y:\n    get:\n" + _schema_ref("./fehlt.yml")}
    (einstieg,) = oa_bundle.laden(_alle(dateien)).einstiege()
    assert (einstieg.erreicht, einstieg.eingebunden_von) == (0, 0) and einstieg.beschriftung == "w.yml (2 Pfade)"


def test_ohne_wurzeldatei_stehen_alle_dateien_als_einstiege_ohne_hinweis():
    satz = oa_bundle.laden(_alle({"x.yml": "type: string\n"}))
    assert [e.beschriftung for e in satz.einstiege()] == ["x.yml"]


def test_angebot_blendet_dateien_ohne_pfade_aus_solange_es_eine_echte_beschreibung_gibt():
    dateien = {
        "api.yml": KOPF + "paths:\n  /x: {}\n",
        "hooks.yml": "openapi: 3.1.0\ninfo: {title: T, version: '1'}\nwebhooks:\n  w: {}\n",
        "leer.yml": KOPF + "paths: {}\n",
        "ohne.yml": KOPF,
    }
    satz = oa_bundle.laden(_alle(dateien))
    angeboten, ausgeblendet = satz.angebot()
    assert [e.datei.pfad for e in angeboten] == ["api.yml", "hooks.yml"]  # Webhooks zählen als echt
    assert [e.datei.pfad for e in ausgeblendet] == ["leer.yml", "ohne.yml"]
    alle, nichts = satz.angebot(auch_bausteine=True)
    assert [e.datei.pfad for e in alle] == ["api.yml", "hooks.yml", "leer.yml", "ohne.yml"] and nichts == []


def test_angebot_ohne_echte_beschreibung_zeigt_alles():
    satz = oa_bundle.laden(_alle({"a.yml": KOPF + "paths: {}\n", "b.yml": KOPF}))
    angeboten, ausgeblendet = satz.angebot()
    assert [e.datei.pfad for e in angeboten] == ["a.yml", "b.yml"] and ausgeblendet == []
    # und ganz ohne Wurzeldatei: alle Dateien (die Prüfung meldet dann das fehlende `openapi:`)
    ohne = oa_bundle.laden(_alle({"x.yml": "type: string\n"}))
    assert [e.datei.pfad for e in ohne.angebot()[0]] == ["x.yml"]


def test_standardantwort_und_eigenschaft_namens_default_werden_aufgeloest_beispielwerte_nicht():
    """Regression: `responses.default` wurde wie ein Beispielwert (`default:`) behandelt, der `$ref` blieb unaufgelöst und die
    Oberfläche meldete beim Aufklappen „Could not resolve reference: Failed to fetch“."""
    dateien = {
        "w.yml": KOPF + "paths:\n  /a:\n    get:\n      responses:\n        default:\n          $ref: ./fehler.yml\n",
        "fehler.yml": (
            "description: Fehler\ncontent:\n  application/json:\n    schema:\n      type: object\n      properties:\n"
            "        default:\n          $ref: ./s.yml\n        example:\n          $ref: ./s.yml\n"
            "      example:\n        $ref: ./gibt-es-nicht.yml\n      default:\n        $ref: ./auch-nicht.yml\n"
        ),
        "s.yml": "type: string\n",
    }
    b = _buendeln(_alle(dateien), "w.yml")
    assert b.ergebnis.befunde == []  # die beiden Verweise in Wertschlüsseln sind keine Verweise: keine Fehler
    spec = b.ergebnis.spec
    schema = spec["paths"]["/a"]["get"]["responses"]["default"]["content"]["application/json"]["schema"]
    assert schema["properties"] == {"default": {"$ref": "#/components/schemas/s"}, "example": {"$ref": "#/components/schemas/s"}}
    assert schema["example"] == {"$ref": "./gibt-es-nicht.yml"} and schema["default"] == {"$ref": "./auch-nicht.yml"}
    assert sorted(ref for ref, _ in oa_parse._alle_refs(spec) if not ref.startswith("#")) == ["./auch-nicht.yml", "./gibt-es-nicht.yml"]


def test_tief_verschachtelte_verweise_mit_mehreren_ebenen_nach_oben():
    kopf = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\n"
    zip_ = _zip(
        {
            "r/common/b.yml": "type: object\nproperties:\n  n: {type: integer}\n",
            "r/services/s/openapi.yml": kopf + "paths:\n  /a:\n    $ref: ./paths/a.yml\n",
            "r/services/s/paths/a.yml": "get:\n  responses:\n    '200':\n      description: ok\n      content:\n        application/json:\n"
            "          schema:\n            $ref: ../../../common/b.yml\n",
        }
    )
    b = _buendeln([zip_], "r/services/s/openapi.yml")
    assert b.ergebnis.befunde == [] and set(oa_parse.schemas(b.ergebnis.spec)) == {"b"}
    assert b.verwendet[-1].endswith("r/common/b.yml")


def test_ohne_wurzeldatei_sind_alle_dateien_kandidaten_und_die_pruefung_meldet_das_fehlende():
    satz = oa_bundle.laden(_alle({"nur.yaml": "type: string\n"}))
    assert [d.pfad for d in satz.kandidaten()] == ["nur.yaml"]
    fehler = _texte(oa_bundle.buendeln(satz, "nur.yaml"), oa_parse.FEHLER)
    assert any("openapi" in f for f in fehler)


def test_unlesbare_wurzel_gibt_keine_spezifikation_aber_die_befunde():
    satz = oa_bundle.laden([("w.yaml", b"openapi: 3.0.3\ninfo: [offen\n")])
    b = oa_bundle.buendeln(satz, "w.yaml")
    assert b.ergebnis.spec is None and len(b.ergebnis.fehler) == 1 and "Zeile" in b.ergebnis.fehler[0].ort


def test_doppelter_schluessel_in_fremder_datei_wird_mit_dateinamen_gemeldet():
    b = _buendeln(_alle({"w.yaml": WURZEL_MIN % "s.yaml", "s.yaml": "type: string\ntype: integer\n"}))
    warn = _texte(b, oa_parse.WARNUNG)
    assert len(warn) == 1 and warn[0].startswith("s.yaml: Zeile 2")


def test_gleich_benannte_uploads_bekommen_eindeutige_pfade():
    satz = oa_bundle.laden([("a.yaml", b"x: 1\n"), ("a.yaml", b"x: 2\n")])
    assert [d.pfad for d in satz.dateien] == ["a.yaml", "a (2).yaml"] and {d.anzeige for d in satz.dateien} == {"a.yaml"}


def test_zu_viele_knoten_werden_abgefangen(monkeypatch):
    monkeypatch.setattr(oa_bundle, "MAX_KNOTEN", 10)
    b = _buendeln(_alle({"w.yaml": WURZEL_MIN % "s.yaml", "s.yaml": "type: string\n"}))
    assert b.ergebnis.spec is None and "Knoten" in b.ergebnis.fehler[0].text


def test_wechselseitiges_einsetzen_explodiert_nicht(monkeypatch):
    """Jede Datei setzt die nächste zweimal ein: 2^40 Knoten. Die Grenze fängt das ab, statt den Speicher zu füllen."""
    monkeypatch.setattr(oa_bundle, "MAX_KNOTEN", 100_000)
    w = "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths: {}\nx-a:\n  $ref: ./d0.yaml\n"
    dateien = {"w.yaml": w}
    for i in range(40):
        dateien[f"d{i}.yaml"] = f"l:\n  $ref: ./d{i + 1}.yaml\nr:\n  $ref: ./d{i + 1}.yaml\n"
    dateien["d40.yaml"] = "ende: 1\n"
    b = _buendeln(_alle(dateien), "w.yaml")
    assert b.ergebnis.spec is None and "Knoten" in b.ergebnis.fehler[0].text


# ---------------------------------------------------------------- ZIP


def test_zip_ueberspringt_unbrauchbares():
    uploads = [
        _zip(
            {
                "ok/openapi.yaml": "openapi: 3.0.3\ninfo: {title: T, version: '1'}\npaths: {}\n",
                "../boese.yaml": "x: 1\n",
                "/absolut.yaml": "x: 1\n",
                "__MACOSX/ok/._openapi.yaml": "binaer",
                ".versteckt.yaml": "x: 1\n",
                "ok/LIESMICH.md": "# kein YAML",
                "ok/bild.png": b"\x89PNG",
            }
        )
    ]
    assert [d.pfad for d in oa_bundle.laden(uploads).dateien] == ["ok/openapi.yaml"]


def test_kein_gueltiges_zip_wird_gemeldet():
    satz = oa_bundle.laden([("kaputt.zip", b"das ist kein zip")])
    assert satz.dateien == [] and "ZIP" in satz.befunde[0].text


def test_zip_mit_zu_vielen_dateien_liest_nur_bis_zur_grenze(monkeypatch):
    monkeypatch.setattr(oa_bundle, "MAX_DATEIEN", 3)
    satz = oa_bundle.laden([_zip({f"d{i}.yaml": "x: 1\n" for i in range(5)})])
    assert len(satz.dateien) == 3 and "3 Dateien" in satz.befunde[0].text


def test_zip_entpackt_zu_gross(monkeypatch):
    monkeypatch.setattr(oa_bundle, "MAX_ENTPACKT_BYTES", 20)
    satz = oa_bundle.laden([_zip({"a.yaml": "x: 1\n", "b.yaml": "y: " + "z" * 40 + "\n"})])
    assert [d.pfad for d in satz.dateien] == ["a.yaml"] and "entpackt größer" in satz.befunde[0].text


def test_zip_einzeldatei_zu_gross(monkeypatch):
    monkeypatch.setattr(oa_bundle, "MAX_EINZEL_BYTES", 10)
    satz = oa_bundle.laden([_zip({"a.yaml": "x: " + "z" * 40 + "\n"})])
    assert satz.dateien[0].roh is None and "größer als" in satz.dateien[0].befunde[0].text


def test_falsche_kodierung_in_einer_datei_betrifft_nur_diese():
    satz = oa_bundle.laden([("alt.yaml", "titel: Größe".encode("latin-1")), ("neu.yaml", "titel: Größe".encode("utf-8"))])
    alt, neu = satz.dateien
    assert alt.roh is None and "UTF-8" in alt.befunde[0].text
    assert neu.roh == {"titel": "Größe"}


def test_zip_inhalt_wird_wie_einzeldateien_gelesen_mit_anzeige_des_zipnamens():
    satz = oa_bundle.laden([_zip({"o/openapi.yaml": "openapi: 3.0.3\n"}, name="mein.zip")])
    assert satz.dateien[0].anzeige == "mein.zip: o/openapi.yaml"


@pytest.mark.parametrize("eingabe", [[], [("a.yaml", b"")]])
def test_leere_eingaben_stuerzen_nicht(eingabe):
    satz = oa_bundle.laden(eingabe)
    for kandidat in satz.kandidaten():
        assert oa_bundle.buendeln(satz, kandidat.pfad).ergebnis.spec is None
