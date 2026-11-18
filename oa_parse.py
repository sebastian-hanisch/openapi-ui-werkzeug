"""OpenAPI-Spezifikation lesen, prüfen und zusammenfassen (ohne Streamlit).

Die Datei wird mit PyYAML gelesen (YAML ist die Obermenge von JSON, JSON-Dateien gehen also auch).
Zwei Abweichungen von PyYAML-Standard, damit die Spezifikation so ankommt, wie sie gemeint ist:

* Nur ``true`` und ``false`` sind Wahrheitswerte. PyYAML liest sonst auch ``no``, ``off`` und ``on`` als Wahrheitswert
  (YAML 1.1); ein Ländercode ``no`` (Norwegen) würde zu ``false``.
* Datums- und Zeitangaben bleiben Text (``2024-05-01``), damit ``example``-Werte unverändert erscheinen.

Die Prüfung ist bewusst klein: Sie findet die Fehler, die eine Oberfläche sichtbar kaputt machen (fehlende Pflichtfelder,
unauflösbare ``$ref``, doppelte ``operationId``, nicht deklarierte Pfadparameter). Sie ist kein vollständiger Validator
gegen das offizielle JSON-Schema der OpenAPI-Spezifikation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

MAX_EINGABE_ZEICHEN = 2_000_000
MAX_AUSGABE_ZEICHEN = 6_000_000
METHODEN = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

FEHLER = "Fehler"
WARNUNG = "Warnung"


@dataclass
class Befund:
    stufe: str
    ort: str
    text: str


@dataclass
class Ergebnis:
    spec: dict | None = None
    befunde: list[Befund] = field(default_factory=list)

    @property
    def fehler(self) -> list[Befund]:
        return [b for b in self.befunde if b.stufe == FEHLER]

    @property
    def warnungen(self) -> list[Befund]:
        return [b for b in self.befunde if b.stufe == WARNUNG]

    @property
    def lesbar(self) -> bool:
        """Es gibt eine Spezifikation, die die Oberfläche zeichnen kann (Warnungen stören nicht)."""
        return self.spec is not None and not self.fehler


class _Lader(yaml.SafeLoader):
    """SafeLoader mit Wahrheitswerten nur für true/false, ohne Datums-Umwandlung und mit Meldung doppelter Schlüssel."""

    doppelte_schluessel: list[tuple[str, int]]


def _resolver_bereinigen() -> None:
    bool_re = re.compile(r"^(?:true|false)$")
    resolver = {k: list(v) for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}
    for erstes_zeichen, liste in resolver.items():
        liste[:] = [
            (tag, regex)
            for tag, regex in liste
            if tag not in ("tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp")
        ]
    for zeichen in "tf":
        resolver.setdefault(zeichen, []).append(("tag:yaml.org,2002:bool", bool_re))
    _Lader.yaml_implicit_resolvers = resolver


_resolver_bereinigen()


def _konstruiere_mapping(lader: _Lader, node: yaml.MappingNode, deep: bool = False):
    lader.flatten_mapping(node)
    gesehen: set = set()
    for schluessel_node, _ in node.value:
        schluessel = lader.construct_object(schluessel_node, deep=True)
        try:
            if schluessel in gesehen:
                lader.doppelte_schluessel.append((str(schluessel), schluessel_node.start_mark.line + 1))
            gesehen.add(schluessel)
        except TypeError:
            pass
    return yaml.SafeLoader.construct_mapping(lader, node, deep=deep)


_Lader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _konstruiere_mapping)


def _lader_fuer(text: str) -> _Lader:
    lader = _Lader(text)
    lader.doppelte_schluessel = []
    return lader


def _zu_json(spec: dict) -> str:
    """JSON-Text der Spezifikation; bricht ab, wenn er unvernünftig groß wird (Alias-Bombe) oder Zyklen enthält."""
    teile: list[str] = []
    laenge = 0
    for stueck in json.JSONEncoder(ensure_ascii=False, check_circular=True).iterencode(spec):
        laenge += len(stueck)
        if laenge > MAX_AUSGABE_ZEICHEN:
            raise ValueError(
                f"Die Spezifikation wird nach dem Auflösen der YAML-Anker größer als {MAX_AUSGABE_ZEICHEN:,} Zeichen "
                "(vermutlich verschachtelte Aliase)."
            )
        teile.append(stueck)
    return "".join(teile)


def aus_bytes(daten: bytes) -> tuple[str, str]:
    """Hochgeladene Bytes → (Text, Fehlermeldung). Genau eines von beiden ist leer. UTF-8, eine Markierung am Anfang (BOM) wird entfernt."""
    if len(daten) > MAX_EINGABE_ZEICHEN * 4:
        return "", f"Die Datei ist mit {len(daten):,} Bytes zu groß."
    try:
        return daten.decode("utf-8-sig"), ""
    except UnicodeDecodeError:
        return "", "Die Datei ist nicht UTF-8-kodiert."


def lesen_roh(text: str) -> tuple[dict | None, list[Befund]]:
    """Text → (Objekt, Befunde des Lesens). Ohne Prüfung als OpenAPI-Datei: auch ein Fragment (nur ein Schema) ist lesbar.

    Das Objekt ist ein reines JSON-Objekt (Schlüssel Text) oder ``None``, wenn der Text nicht lesbar war.
    """
    befunde: list[Befund] = []
    if not text.strip():
        return None, [Befund(FEHLER, "Datei", "Die Eingabe ist leer.")]
    if len(text) > MAX_EINGABE_ZEICHEN:
        return None, [
            Befund(FEHLER, "Datei", f"Die Eingabe hat {len(text):,} Zeichen; erlaubt sind höchstens {MAX_EINGABE_ZEICHEN:,}.")
        ]
    lader = _lader_fuer(text)
    try:
        roh = lader.get_single_data()
    except yaml.YAMLError as exc:
        return None, [Befund(FEHLER, _ort(exc), _yaml_meldung(exc))]
    except RecursionError:
        return None, [Befund(FEHLER, "Datei", "Die Verschachtelung ist zu tief.")]
    finally:
        lader.dispose()
    for schluessel, zeile in lader.doppelte_schluessel:
        befunde.append(Befund(WARNUNG, f"Zeile {zeile}", f"Der Schlüssel „{schluessel}“ kommt doppelt vor; es gilt der letzte."))
    if not isinstance(roh, dict):
        befunde.append(Befund(FEHLER, "Datei", "Die oberste Ebene muss ein Objekt (Schlüssel: Wert) sein."))
        return None, befunde
    try:
        return json.loads(_zu_json(roh)), befunde
    except (ValueError, TypeError) as exc:
        befunde.append(Befund(FEHLER, "Datei", str(exc)))
        return None, befunde


def lesen(text: str) -> Ergebnis:
    """Text → Ergebnis. ``spec`` ist ein reines JSON-Objekt (Schlüssel Text), wenn der Text lesbar war."""
    spec, befunde = lesen_roh(text)
    erg = Ergebnis(spec=spec, befunde=befunde)
    if spec is not None:
        erg.befunde.extend(pruefen(spec))
    return erg


def _ort(exc: yaml.YAMLError) -> str:
    marke = getattr(exc, "problem_mark", None)
    if marke is None:
        return "Datei"
    return f"Zeile {marke.line + 1}, Spalte {marke.column + 1}"


def _yaml_meldung(exc: yaml.YAMLError) -> str:
    problem = getattr(exc, "problem", None) or str(exc)
    kontext = getattr(exc, "context", None)
    return f"{kontext}: {problem}" if kontext else str(problem)


def version(spec: dict) -> str | None:
    """„3.0.3“, „3.1.0“, „2.0“ oder ``None``."""
    v = spec.get("openapi", spec.get("swagger"))
    return str(v) if v is not None else None


def ist_v2(spec: dict) -> bool:
    return "swagger" in spec and "openapi" not in spec


def pruefen(spec: dict, *, externe_melden: bool = True) -> list[Befund]:
    """Befunde zu einer Spezifikation. ``externe_melden=False``: ``$ref`` auf Dateien/URLs nicht melden (das macht dann der Aufrufer, z. B. das Bündeln)."""
    b: list[Befund] = []
    v = version(spec)
    if v is None:
        b.append(Befund(FEHLER, "oberste Ebene", "Es fehlt `openapi: 3.x.x` (bzw. `swagger: \"2.0\"`)."))
    elif not (v.startswith("3.") or v == "2.0"):
        b.append(Befund(FEHLER, "openapi", f"Version „{v}“ wird nicht unterstützt (erlaubt: 2.0 und 3.x)."))
    info = spec.get("info")
    if not isinstance(info, dict):
        b.append(Befund(FEHLER, "info", "Der Block `info` fehlt."))
    else:
        for pflicht in ("title", "version"):
            if not info.get(pflicht):
                b.append(Befund(FEHLER, f"info.{pflicht}", f"`info.{pflicht}` fehlt (Pflichtfeld)."))
    paths = spec.get("paths")
    ohne_pfade_ok = bool(v and v.startswith("3.1") and (spec.get("components") or spec.get("webhooks")))
    if paths is None:
        if not ohne_pfade_ok:
            b.append(Befund(FEHLER, "paths", "Der Block `paths` fehlt."))
    elif not isinstance(paths, dict):
        b.append(Befund(FEHLER, "paths", "`paths` muss ein Objekt sein."))
    else:
        b.extend(_pfade_pruefen(spec, paths))
    b.extend(_refs_pruefen(spec, externe_melden))
    return b


_PFAD_PARAM = re.compile(r"\{([^}/]+)\}")


def _pfade_pruefen(spec: dict, paths: dict) -> list[Befund]:
    b: list[Befund] = []
    ids: dict[str, str] = {}
    for pfad, item in paths.items():
        if not str(pfad).startswith("/"):
            b.append(Befund(WARNUNG, f"paths.{pfad}", "Ein Pfad muss mit `/` beginnen."))
        if not isinstance(item, dict):
            b.append(Befund(FEHLER, f"paths.{pfad}", "Ein Pfadeintrag muss ein Objekt sein."))
            continue
        gemeinsam = item.get("parameters", [])
        for methode in METHODEN:
            op = item.get(methode)
            if op is None:
                continue
            ort = f"{methode.upper()} {pfad}"
            if not isinstance(op, dict):
                b.append(Befund(FEHLER, ort, "Eine Operation muss ein Objekt sein."))
                continue
            if not op.get("responses"):
                b.append(Befund(WARNUNG, ort, "Die Operation hat keine `responses` (Pflichtfeld in OpenAPI 3.0 und 2.0)."))
            op_id = op.get("operationId")
            if op_id is not None:
                if op_id in ids:
                    b.append(Befund(WARNUNG, ort, f"`operationId` „{op_id}“ gibt es schon bei {ids[op_id]}."))
                else:
                    ids[op_id] = ort
            b.extend(_pfadparameter_pruefen(spec, pfad, ort, gemeinsam, op.get("parameters", [])))
    return b


def _pfadparameter_pruefen(spec: dict, pfad: str, ort: str, gemeinsam, eigene) -> list[Befund]:
    deklariert: set[str] = set()
    for p in list(gemeinsam if isinstance(gemeinsam, list) else []) + list(eigene if isinstance(eigene, list) else []):
        if isinstance(p, dict) and "$ref" in p:
            p = _aufloesen(spec, p["$ref"]) or {}
        if isinstance(p, dict) and p.get("in") == "path" and p.get("name"):
            deklariert.add(str(p["name"]))
    return [
        Befund(WARNUNG, ort, f"Der Pfadparameter `{{{name}}}` ist nicht als Parameter (`in: path`) beschrieben.")
        for name in _PFAD_PARAM.findall(pfad)
        if name not in deklariert
    ]


def _aufloesen(spec: dict, ref: str):
    """Lokaler ``$ref`` (``#/components/schemas/X``) → Zielobjekt oder ``None``."""
    if not isinstance(ref, str) or not ref.startswith("#"):
        return None
    ziel = spec
    for teil in ref[1:].lstrip("/").split("/") if ref != "#" else []:
        teil = teil.replace("~1", "/").replace("~0", "~")
        if isinstance(ziel, dict) and teil in ziel:
            ziel = ziel[teil]
        elif isinstance(ziel, list) and teil.isdigit() and int(teil) < len(ziel):
            ziel = ziel[int(teil)]
        else:
            return None
    return ziel


def _alle_refs(knoten, pfad="") :
    """Alle ``$ref``-Werte mit Fundort, ohne Rekursion (tief verschachtelte Dateien)."""
    stapel = [(knoten, pfad)]
    while stapel:
        k, p = stapel.pop()
        if isinstance(k, dict):
            for schluessel, wert in k.items():
                if schluessel == "$ref" and isinstance(wert, str):
                    yield wert, p
                else:
                    stapel.append((wert, f"{p}.{schluessel}" if p else str(schluessel)))
        elif isinstance(k, list):
            for i, wert in enumerate(k):
                stapel.append((wert, f"{p}[{i}]"))


def _refs_pruefen(spec: dict, externe_melden: bool = True) -> list[Befund]:
    b: list[Befund] = []
    for ref, ort in _alle_refs(spec):
        if ref.startswith("#"):
            if _aufloesen(spec, ref) is None:
                b.append(Befund(FEHLER, ort, f"`$ref` „{ref}“ zeigt auf nichts."))
        elif externe_melden:
            b.append(
                Befund(
                    WARNUNG,
                    ort,
                    f"`$ref` „{ref}“ verweist auf eine andere Datei oder URL; die Oberfläche bekommt nur diese eine Datei "
                    "und kann sie nicht auflösen.",
                )
            )
    return b


@dataclass
class Operation:
    methode: str
    pfad: str
    zusammenfassung: str
    tags: list[str]
    veraltet: bool
    operation_id: str


def operationen(spec: dict) -> list[Operation]:
    paths = spec.get("paths")
    ergebnis: list[Operation] = []
    if not isinstance(paths, dict):
        return ergebnis
    for pfad, item in paths.items():
        if not isinstance(item, dict):
            continue
        for methode in METHODEN:
            op = item.get(methode)
            if isinstance(op, dict):
                tags = op.get("tags") if isinstance(op.get("tags"), list) else []
                ergebnis.append(
                    Operation(
                        methode=methode.upper(),
                        pfad=str(pfad),
                        zusammenfassung=str(op.get("summary") or ""),
                        tags=[str(t) for t in tags],
                        veraltet=bool(op.get("deprecated", False)),
                        operation_id=str(op.get("operationId") or ""),
                    )
                )
    return ergebnis


def schemas(spec: dict) -> dict:
    """Die benannten Schemas (OpenAPI 3: components.schemas, 2.0: definitions)."""
    comp = spec.get("components")
    if isinstance(comp, dict) and isinstance(comp.get("schemas"), dict):
        return comp["schemas"]
    defs = spec.get("definitions")
    return defs if isinstance(defs, dict) else {}


def kennzahlen(spec: dict) -> dict[str, object]:
    ops = operationen(spec)
    tags = {t for o in ops for t in o.tags}
    return {
        "version": version(spec) or "?",
        "titel": str((spec.get("info") or {}).get("title", "")) if isinstance(spec.get("info"), dict) else "",
        "operationen": len(ops),
        "pfade": len({o.pfad for o in ops}),
        "tags": len(tags),
        "schemas": len(schemas(spec)),
        "veraltet": sum(1 for o in ops if o.veraltet),
    }
