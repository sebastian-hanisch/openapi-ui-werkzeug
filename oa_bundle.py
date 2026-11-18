"""Mehrere Dateien einer OpenAPI-Beschreibung zu einer Spezifikation bündeln (ohne Streamlit).

Große Beschreibungen liegen oft in einem Ordner: eine Wurzeldatei (``openapi.yaml``) und dazu Dateien für Pfade, Schemas und
Parameter, verbunden durch ``$ref: ./schemas/Sendung.yaml`` oder ``$ref: ./common.yaml#/components/parameters/Limit``.
Die Swagger UI im Rahmen bekommt aber nur eine Seite und kann solche Verweise nicht auflösen. Dieses Modul löst sie vorher auf:

* **Schemas, Parameter, Antworten** (alles unter ``components/<Abschnitt>/<Name>``, bei Swagger 2.0 unter ``definitions``, ``parameters``,
  ``responses``) wandern in den Abschnitt ``components`` der Wurzeldatei und behalten ihren Namen. Ein ``$ref`` auf eine ganze
  Datei an einer Schema-Stelle (``schema``, ``items``, ``properties``, ``allOf`` …) wird dort als Schema abgelegt, benannt nach der Datei.
  So bleiben die Namen in der Oberfläche sichtbar, und rekursive Schemas (ein Knoten verweist auf sich selbst) funktionieren.
* **Alles andere** (zum Beispiel ein Pfadeintrag in ``paths/sendungen.yaml``) wird an Ort und Stelle eingesetzt.
* **Ein Verweis im Kreis** auf etwas, das nicht benannt abgelegt werden konnte, wird als Schema abgelegt.

Die Dateien kommen als Upload: einzeln, mehrere zusammen oder ein ZIP des Ordners (nur das ZIP behält die Ordnerstruktur). Ohne
Ordnerstruktur wird ein Verweis ``./schemas/Sendung.yaml`` über den Dateinamen gefunden, solange der eindeutig ist.
"""
from __future__ import annotations

import io
import json
import posixpath
import re
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from urllib.parse import unquote

import oa_parse
from oa_parse import FEHLER, WARNUNG, Befund, Ergebnis

ENDUNGEN = (".yaml", ".yml", ".json")
MAX_DATEIEN = 300
MAX_EINZEL_BYTES = oa_parse.MAX_EINGABE_ZEICHEN * 4
MAX_ENTPACKT_BYTES = 25_000_000
MAX_KNOTEN = 2_000_000  # Knoten der gebündelten Spezifikation; fängt Dateien ab, die sich gegenseitig vielfach einsetzen

V3_ABSCHNITTE = ("schemas", "responses", "parameters", "examples", "requestBodies", "headers", "securitySchemes", "links", "callbacks", "pathItems")
V2_ABSCHNITTE = ("definitions", "parameters", "responses")
_SCHEMA_STELLEN_LETZTER = {"schema", "items", "additionalProperties", "not", "contains", "propertyNames", "unevaluatedProperties", "if", "then", "else", "additionalItems"}
_SCHEMA_STELLEN_VORLETZTER = {"properties", "allOf", "oneOf", "anyOf", "patternProperties", "prefixItems", "schemas", "definitions", "$defs"}
_WERT_SCHLUESSEL = {"example", "default", "enum", "const"}  # hier stehen Beispielwerte, kein $ref (außer in Namenskarten, s. u.)
# Objekte, deren Schlüssel frei gewählte Namen sind (Antwortcodes und „default“, Eigenschaften, Beispiele, Medientypen …): ein Schlüssel
# „default“ ist dort ein Name, kein Wert, und sein Inhalt wird wie alles andere aufgelöst.
_NAMENSKARTEN = {
    "responses", "properties", "patternProperties", "headers", "content", "examples", "encoding", "links", "callbacks", "variables",
    "schemas", "parameters", "requestBodies", "securitySchemes", "pathItems", "definitions", "mapping", "scopes",
}
_URL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _finde_datei(nach_pfad: dict[str, "Datei"], datei_teil: str, von_pfad: str) -> tuple["Datei | None", str]:
    """Dateiteil eines ``$ref`` (ab der Datei ``von_pfad``) → (Datei, ""), oder (``None``, Fehlertext). Ohne Nebenwirkung."""
    teil = unquote(datei_teil).replace("\\", "/")
    kandidat = posixpath.normpath(posixpath.join(posixpath.dirname(von_pfad), teil))
    ziel = nach_pfad.get(kandidat)
    if ziel is not None:
        return ziel, ""
    # Ohne Ordnerstruktur (Dateien einzeln hochgeladen): über das Ende des Pfades, dann über den Dateinamen suchen.
    rest = posixpath.normpath(teil)
    while rest.startswith(("../", "./")):
        rest = rest.split("/", 1)[1]
    for stichwort in (rest, posixpath.basename(rest)):
        treffer = [p for p in nach_pfad if p == stichwort or p.endswith("/" + stichwort)]
        if len(treffer) == 1:
            return nach_pfad[treffer[0]], ""
        if len(treffer) > 1:
            return None, (
                f"`$ref` auf „{datei_teil}“ ist nicht eindeutig: {len(treffer)} hochgeladene Dateien passen. "
                "Laden Sie den Ordner als ZIP hoch, dann gilt die Ordnerstruktur."
            )
    return None, f"`$ref` auf die Datei „{datei_teil}“: sie ist nicht hochgeladen."


@dataclass
class Datei:
    pfad: str  # eindeutig; Grundlage der $ref-Auflösung ("api/schemas/Sendung.yaml" oder nur "Sendung.yaml")
    anzeige: str  # wie hochgeladen
    roh: dict | None  # gelesener Inhalt (YAML-Anker aufgelöst), ``None`` wenn nicht lesbar
    befunde: list[Befund] = field(default_factory=list)  # Befunde beim Lesen dieser Datei

    @property
    def ist_wurzel(self) -> bool:
        return isinstance(self.roh, dict) and ("openapi" in self.roh or "swagger" in self.roh)

    def _anzahl(self, schluessel: str) -> int:
        eintrag = self.roh.get(schluessel) if isinstance(self.roh, dict) else None
        return len(eintrag) if isinstance(eintrag, dict) else 0

@dataclass
class Einstieg:
    """Eine Datei, die als Einstieg in Frage kommt, mit dem, was ihre Stellung im Dateienverbund verrät."""

    datei: Datei
    pfade: int  # Einträge unter ``paths``
    webhooks: int  # Einträge unter ``webhooks``
    eingebunden_von: int  # Zahl anderer Dateien, die diese per ``$ref`` einbinden (Baustein, wenn > 0)
    erreicht: int  # Zahl anderer Dateien, die von hier aus per ``$ref`` erreichbar sind, auch mittelbar

    @property
    def hat_operationen(self) -> bool:
        return self.pfade > 0 or self.webhooks > 0

    @property
    def ist_freie_beschreibung(self) -> bool:
        """Beschreibt Pfade/Webhooks und wird von keiner anderen Datei eingebunden: so sieht ein Einstieg aus."""
        return self.hat_operationen and self.eingebunden_von == 0

    @property
    def beschriftung(self) -> str:
        """Name mit einem Hinweis, was in der Datei steht und wie sie im Verbund steht (für die Auswahl)."""
        if not self.datei.ist_wurzel:
            return self.datei.anzeige
        if not self.hat_operationen:
            return f"{self.datei.anzeige} (nur Bausteine, keine Pfade)"
        teile = []
        if self.pfade:
            teile.append(f"{self.pfade} Pfad" if self.pfade == 1 else f"{self.pfade} Pfade")
        if self.webhooks:
            teile.append(f"{self.webhooks} Webhook" if self.webhooks == 1 else f"{self.webhooks} Webhooks")
        if self.erreicht:
            teile.append(f"bindet {self.erreicht} Dateien ein" if self.erreicht > 1 else "bindet 1 Datei ein")
        if self.eingebunden_von:
            teile.append("selbst eingebunden" if self.eingebunden_von == 1 else f"selbst von {self.eingebunden_von} Dateien eingebunden")
        return f"{self.datei.anzeige} ({', '.join(teile)})"


def _verweisgraph(dateien: list[Datei]) -> dict[str, set[str]]:
    """Pfad → Pfade der Dateien, auf die sie per ``$ref`` verweist (nur auflösbare, nicht auf sich selbst)."""
    nach_pfad = {d.pfad: d for d in dateien}
    graph: dict[str, set[str]] = {d.pfad: set() for d in dateien}
    for d in dateien:
        if d.roh is None:
            continue
        for ref, _ort in oa_parse._alle_refs(d.roh):
            datei_teil = ref.partition("#")[0]
            if not datei_teil or ref.startswith("#") or _URL.match(ref):
                continue
            ziel, _fehler = _finde_datei(nach_pfad, datei_teil, d.pfad)
            if ziel is not None and ziel.pfad != d.pfad:
                graph[d.pfad].add(ziel.pfad)
    return graph


def _erreichbar(graph: dict[str, set[str]], start: str) -> set[str]:
    gesehen: set[str] = set()
    stapel = [start]
    while stapel:
        for nachbar in graph.get(stapel.pop(), ()):
            if nachbar not in gesehen and nachbar != start:
                gesehen.add(nachbar)
                stapel.append(nachbar)
    return gesehen


@dataclass
class Satz:
    """Alle hochgeladenen Dateien (ZIPs ausgepackt)."""

    dateien: list[Datei] = field(default_factory=list)
    befunde: list[Befund] = field(default_factory=list)  # Probleme, die zu keiner einzelnen Datei gehören (ZIP)

    def einstiege(self) -> list[Einstieg]:
        """Dateien, die als Wurzel in Frage kommen (mit ``openapi:``/``swagger:``; gibt es keine, alle), beste Vorauswahl zuerst.

        Rein aus der Struktur, ohne Vermutung über Namen: Ein Einstieg beschreibt Pfade oder Webhooks und wird von keiner anderen
        Datei eingebunden; Bausteine (auch solche mit ``openapi:``-Kopf und ``paths: {}``) werden irgendwo per ``$ref`` eingebunden.
        Reihenfolge: freie Beschreibungen vor eingebundenen, diese vor Dateien ohne Pfade; darin mehr Pfade, dann mehr erreichte Dateien
        zuerst, sonst die Reihenfolge des Hochladens.
        """
        wurzeln = [d for d in self.dateien if d.ist_wurzel] or list(self.dateien)
        graph = _verweisgraph(self.dateien)
        eingebunden = {d.pfad: 0 for d in self.dateien}
        for quelle, ziele in graph.items():
            for ziel in ziele:
                eingebunden[ziel] += 1
        alle = [
            Einstieg(d, d._anzahl("paths"), d._anzahl("webhooks"), eingebunden[d.pfad], len(_erreichbar(graph, d.pfad)))
            for d in wurzeln
        ]
        return sorted(
            alle,
            key=lambda e: (0 if e.ist_freie_beschreibung else 1 if e.hat_operationen else 2, -(e.pfade + e.webhooks), -e.erreicht),
        )

    def angebot(self, auch_bausteine: bool = False) -> tuple[list[Einstieg], list[Einstieg]]:
        """(angebotene, ausgeblendete) Einstiege. Dateien ohne Pfade und Webhooks (Bausteine) werden ausgeblendet, sobald es
        mindestens eine Beschreibung mit Pfaden oder Webhooks gibt; gibt es keine, bleibt alles sichtbar (sonst wäre die Liste leer)."""
        alle = self.einstiege()
        echte = [e for e in alle if e.hat_operationen]
        if auch_bausteine or not echte:
            return alle, []
        return echte, [e for e in alle if not e.hat_operationen]

    def kandidaten(self) -> list[Datei]:
        """Die Einstiegsdateien in der Reihenfolge von :meth:`einstiege` (die erste ist die Vorauswahl)."""
        return [e.datei for e in self.einstiege()]


@dataclass
class Buendel:
    ergebnis: Ergebnis
    verwendet: list[str] = field(default_factory=list)  # Anzeigenamen der Dateien, aus denen die Spezifikation besteht
    unbenutzt: list[str] = field(default_factory=list)  # hochgeladen, aber von der Wurzel aus nicht erreicht


# ---------------------------------------------------------------- Laden

def _eindeutig(pfad: str, belegt: set[str]) -> str:
    kandidat, n = pfad, 2
    stamm, endung = posixpath.splitext(pfad)
    while kandidat in belegt:
        kandidat = f"{stamm} ({n}){endung}"
        n += 1
    belegt.add(kandidat)
    return kandidat


def _datei_aufnehmen(satz: Satz, belegt: set[str], pfad: str, anzeige: str, daten: bytes | None, fehler: str = "") -> None:
    pfad = _eindeutig(pfad, belegt)
    if daten is not None and not fehler:
        text, fehler = oa_parse.aus_bytes(daten)
    if fehler:
        satz.dateien.append(Datei(pfad, anzeige, None, [Befund(FEHLER, "Datei", fehler)]))
        return
    roh, befunde = oa_parse.lesen_roh(text)
    satz.dateien.append(Datei(pfad, anzeige, roh, befunde))


def _zip_pfad(name: str) -> str | None:
    """Pfad im ZIP → normalisierter Pfad mit ``/``; ``None`` für Unbrauchbares (Absolutes, ``..``, versteckte Dateien, macOS-Reste)."""
    pfad = posixpath.normpath(name.replace("\\", "/"))
    teile = pfad.split("/")
    if pfad.startswith("/") or ".." in teile or re.match(r"^[A-Za-z]:", pfad):
        return None
    if any(t.startswith(".") or t == "__MACOSX" for t in teile):
        return None
    return pfad if pfad.lower().endswith(ENDUNGEN) else None


def _zip_lesen(name: str, daten: bytes, satz: Satz, belegt: set[str], gesamt: int) -> int:
    try:
        zf = zipfile.ZipFile(io.BytesIO(daten))
    except zipfile.BadZipFile:
        satz.befunde.append(Befund(FEHLER, name, "Das ist keine gültige ZIP-Datei."))
        return gesamt
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            pfad = _zip_pfad(info.filename)
            if pfad is None:
                continue
            if len(satz.dateien) >= MAX_DATEIEN:
                satz.befunde.append(Befund(FEHLER, name, f"Mehr als {MAX_DATEIEN} Dateien; der Rest wird nicht gelesen."))
                break
            anzeige = f"{name}: {pfad}"
            try:
                with zf.open(info) as f:
                    inhalt = f.read(MAX_EINZEL_BYTES + 1)
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile, EOFError, OSError) as exc:
                _datei_aufnehmen(satz, belegt, pfad, anzeige, None, f"Nicht lesbar aus dem ZIP ({type(exc).__name__}; verschlüsselt?).")
                continue
            gesamt += len(inhalt)
            if gesamt > MAX_ENTPACKT_BYTES:
                satz.befunde.append(Befund(FEHLER, name, f"Das ZIP ist entpackt größer als {MAX_ENTPACKT_BYTES:,} Bytes; der Rest wird nicht gelesen."))
                break
            if len(inhalt) > MAX_EINZEL_BYTES:
                _datei_aufnehmen(satz, belegt, pfad, anzeige, None, f"Die Datei ist größer als {MAX_EINZEL_BYTES:,} Bytes.")
            else:
                _datei_aufnehmen(satz, belegt, pfad, anzeige, inhalt)
    return gesamt


def laden(uploads: Sequence[tuple[str, bytes]]) -> Satz:
    """(Name, Bytes) je Upload → Satz. ZIPs werden ausgepackt (Ordnerstruktur bleibt), alles andere ist eine Datei."""
    satz = Satz()
    belegt: set[str] = set()
    gesamt = 0
    for name, daten in uploads:
        if len(satz.dateien) >= MAX_DATEIEN:
            satz.befunde.append(Befund(FEHLER, name, f"Mehr als {MAX_DATEIEN} Dateien; der Rest wird nicht gelesen."))
            break
        if name.lower().endswith(".zip"):
            gesamt = _zip_lesen(name, daten, satz, belegt, gesamt)
        else:
            sauber = name.replace("\\", "/")
            _datei_aufnehmen(satz, belegt, posixpath.basename(sauber) or sauber, name, daten)
    return satz


# ---------------------------------------------------------------- Bündeln

class _ZuGross(Exception):
    pass


def _name_sauber(name: str) -> str:
    return name.replace("/", "_").replace("~", "_")


class _Buendler:
    def __init__(self, satz: Satz, wurzel: Datei):
        self.nach_pfad = {d.pfad: d for d in satz.dateien}
        self.wurzel = wurzel
        self.v2 = oa_parse.ist_v2(wurzel.roh or {})
        self.abschnitte = V2_ABSCHNITTE if self.v2 else V3_ABSCHNITTE
        self.befunde: list[Befund] = []
        self.verwendet: list[Datei] = [wurzel]
        self.abgelegt: list[tuple[str, str, object]] = []  # (Abschnitt, Name, Inhalt)
        self.adresse: dict[tuple[str, str], str] = {}  # (Dateipfad, Zeiger) → interner Verweis
        self.belegt: dict[str, set[str]] = {a: set() for a in self.abschnitte}
        self.stapel: list[tuple[str, str]] = []
        self.gemeldet: set[tuple[str, str]] = set()
        self.knoten = 0
        self._belegung_aus_wurzel()

    # -- Hilfen
    def _belegung_aus_wurzel(self) -> None:
        """Namen der Wurzel sind belegt. Steht dort ``Sendung: {$ref: ./schemas/Sendung.yaml}``, ist das der Name dieses Ziels."""
        roh = self.wurzel.roh or {}
        quelle = roh if self.v2 else roh.get("components")
        if not isinstance(quelle, dict):
            return
        for abschnitt in self.abschnitte:
            inhalt = quelle.get(abschnitt)
            if not isinstance(inhalt, dict):
                continue
            self.belegt[abschnitt].update(str(n) for n in inhalt)
            for name, wert in inhalt.items():
                ref = wert.get("$ref") if isinstance(wert, dict) else None
                if not isinstance(ref, str) or ref.startswith("#") or _URL.match(ref):
                    continue
                datei_teil, _, zeiger = ref.partition("#")
                ziel, _fehler = self._suche(datei_teil, self.wurzel)
                if ziel is not None and ziel.roh is not None and ziel is not self.wurzel:
                    self.adresse.setdefault((ziel.pfad, zeiger.rstrip("/")), self._intern(abschnitt, str(name)))

    def _melden(self, stufe: str, datei: Datei, ort: str, schluessel: str, text: str) -> None:
        """Jede Meldung je Datei und Schlüssel nur einmal (derselbe fehlende Verweis steht oft vielfach)."""
        if (datei.pfad, schluessel) in self.gemeldet:
            return
        self.gemeldet.add((datei.pfad, schluessel))
        vorsatz = "" if datei is self.wurzel else f"{datei.anzeige}: "
        self.befunde.append(Befund(stufe, f"{vorsatz}{ort}".rstrip(": ") or "Datei", text))

    def _intern(self, abschnitt: str, name: str) -> str:
        return f"#/{abschnitt}/{name}" if self.v2 else f"#/components/{abschnitt}/{name}"

    def _frei(self, abschnitt: str, name: str) -> str:
        name = _name_sauber(name) or "Schema"
        kandidat, n = name, 2
        while kandidat in self.belegt[abschnitt]:
            kandidat = f"{name}_{n}"
            n += 1
        self.belegt[abschnitt].add(kandidat)
        return kandidat

    def _suche(self, datei_teil: str, von: Datei) -> tuple[Datei | None, str]:
        return _finde_datei(self.nach_pfad, datei_teil, von.pfad)

    def _finde(self, datei_teil: str, von: Datei, ort: str) -> Datei | None:
        ziel, fehler = self._suche(datei_teil, von)
        if ziel is None:
            self._melden(FEHLER, von, ort, datei_teil, fehler)
            return None
        if ziel.roh is None:
            fehler = "; ".join(b.text for b in ziel.befunde if b.stufe == FEHLER) or "nicht lesbar"
            self._melden(FEHLER, von, ort, datei_teil, f"`$ref` auf „{datei_teil}“: die Datei ist nicht lesbar ({fehler}).")
            return None
        if ziel not in self.verwendet:
            self.verwendet.append(ziel)
            for b in ziel.befunde:
                self.befunde.append(Befund(b.stufe, f"{ziel.anzeige}: {b.ort}", b.text))
        return ziel

    # -- Abschnitt und Name für das Ablegen
    @staticmethod
    def _zeiger_teile(zeiger: str) -> list[str]:
        return [t.replace("~1", "/").replace("~0", "~") for t in zeiger.split("/")[1:]] if zeiger else []

    def _ablageplatz(self, ort: tuple[str, ...]) -> tuple[str, str] | None:
        """Ist die Stelle selbst ein benannter Platz in der Wurzel (``components/schemas/X``)? → (Abschnitt, Name)."""
        if self.v2:
            if len(ort) == 2 and ort[0] in self.abschnitte:
                return ort[0], ort[1]
        elif len(ort) == 3 and ort[0] == "components" and ort[1] in self.abschnitte:
            return ort[1], ort[2]
        return None

    def _benannt(self, teile: list[str]) -> tuple[str, str] | None:
        """Gehört das Ziel in einen benannten Abschnitt? → (Abschnitt, Name)."""
        if self.v2:
            if len(teile) == 2 and teile[0] in self.abschnitte:
                return teile[0], teile[1]
        elif len(teile) == 3 and teile[0] == "components" and teile[1] in self.abschnitte:
            return teile[1], teile[2]
        return None

    @staticmethod
    def _schema_stelle(ort: tuple[str, ...]) -> bool:
        if not ort:
            return False
        return ort[-1] in _SCHEMA_STELLEN_LETZTER or (len(ort) >= 2 and ort[-2] in _SCHEMA_STELLEN_VORLETZTER)

    def _schema_name(self, ziel: Datei, teile: list[str]) -> tuple[str, str]:
        name = teile[-1] if teile else posixpath.splitext(posixpath.basename(ziel.pfad))[0]
        return ("definitions" if self.v2 else "schemas"), name

    # -- Kopieren und Auflösen
    def kopie(self, knoten, datei: Datei, ort: tuple[str, ...]):
        self.knoten += 1
        if self.knoten > MAX_KNOTEN:
            raise _ZuGross
        if isinstance(knoten, dict):
            ref = knoten.get("$ref")
            if isinstance(ref, str):
                return self._verweis(knoten, ref, datei, ort)
            # In einer Namenskarte (``responses``, ``properties`` …) sind die Schlüssel frei gewählte Namen, auch „default“ oder „example“
            namenskarte = bool(ort) and ort[-1] in _NAMENSKARTEN
            return {
                s: (w if s in _WERT_SCHLUESSEL and not namenskarte else self.kopie(w, datei, ort + (str(s),)))
                for s, w in knoten.items()
            }
        if isinstance(knoten, list):
            return [self.kopie(w, datei, ort + (str(i),)) for i, w in enumerate(knoten)]
        return knoten

    def _verweis(self, knoten: dict, ref: str, datei: Datei, ort: tuple[str, ...]):
        rest = {s: self.kopie(w, datei, ort + (str(s),)) for s, w in knoten.items() if s != "$ref"}
        ort_text = ".".join(ort)
        if _URL.match(ref):
            self._melden(
                WARNUNG, datei, ort_text, ref,
                f"`$ref` „{ref}“ verweist auf eine Adresse im Netz. Das Werkzeug lädt sie nicht; die Oberfläche versucht es im Browser, "
                "das klappt nur mit Internetzugang und wenn der Server Zugriffe von anderen Adressen erlaubt (CORS).",
            )
            return {"$ref": ref, **rest}
        if ref.startswith("#") and datei is self.wurzel:
            return {"$ref": ref, **rest}
        datei_teil, _, zeiger = ref.partition("#")
        ziel_datei = self._finde(datei_teil, datei, ort_text) if datei_teil else datei
        if ziel_datei is None:
            return {"$ref": ref, **rest}
        zeiger = zeiger.rstrip("/")
        if zeiger and not zeiger.startswith("/"):
            self._melden(FEHLER, datei, ort_text, ref, f"`$ref` „{ref}“: nach `#` muss ein Pfad mit `/` folgen.")
            return {"$ref": ref, **rest}
        if ziel_datei is self.wurzel:
            if oa_parse._aufloesen(self.wurzel.roh, "#" + zeiger) is None:
                self._melden(FEHLER, datei, ort_text, ref, f"`$ref` „{ref}“ zeigt auf nichts.")
                return {"$ref": ref, **rest}
            return {"$ref": "#" + zeiger, **rest}
        ziel = oa_parse._aufloesen(ziel_datei.roh, "#" + zeiger)
        if ziel is None:
            self._melden(FEHLER, datei, ort_text, ref, f"`$ref` „{ref}“ zeigt auf nichts.")
            return {"$ref": ref, **rest}

        schluessel = (ziel_datei.pfad, zeiger)
        teile = self._zeiger_teile(zeiger)
        platz = self._ablageplatz(ort)
        if schluessel in self.adresse and not (platz and self._intern(*platz) == self.adresse[schluessel]):
            return {"$ref": self.adresse[schluessel], **rest}
        if platz:  # die Stelle ist selbst ein benannter Platz der Wurzel: dort einsetzen, Name bleibt
            self.adresse[schluessel] = self._intern(*platz)
            return self._einsetzen(ziel, rest, schluessel, ziel_datei, ort)
        if schluessel in self.stapel:  # Kreis ohne benannte Stelle: als Schema ablegen
            ziel_ablage = self._schema_name(ziel_datei, teile)
        else:
            ziel_ablage = self._benannt(teile) or (self._schema_name(ziel_datei, teile) if self._schema_stelle(ort) else None)
        if ziel_ablage is None:
            return self._einsetzen(ziel, rest, schluessel, ziel_datei, ort)
        abschnitt, name = ziel_ablage
        name = self._frei(abschnitt, name)
        adresse = self._intern(abschnitt, name)
        self.adresse[schluessel] = adresse
        inhalt = self._kopie_von(ziel, ziel_datei, schluessel, ("components", abschnitt, name))
        self.abgelegt.append((abschnitt, name, inhalt))
        return {"$ref": adresse, **rest}

    def _kopie_von(self, ziel, ziel_datei: Datei, schluessel, ort):
        self.stapel.append(schluessel)
        try:
            return self.kopie(ziel, ziel_datei, ort)
        finally:
            self.stapel.pop()

    def _einsetzen(self, ziel, rest: dict, schluessel, ziel_datei: Datei, ort):
        inhalt = self._kopie_von(ziel, ziel_datei, schluessel, ort)
        if isinstance(inhalt, dict):
            return {**inhalt, **rest}
        return inhalt


def buendeln(satz: Satz, wurzel_pfad: str) -> Buendel:
    """Wurzeldatei samt aller Dateien, auf die sie verweist, zu einer Spezifikation zusammenfassen und prüfen."""
    wurzel = next((d for d in satz.dateien if d.pfad == wurzel_pfad), None)
    if wurzel is None:
        return Buendel(Ergebnis(None, [Befund(FEHLER, "Datei", "Die Wurzeldatei ist nicht in der Auswahl.")]))
    if wurzel.roh is None:
        return Buendel(Ergebnis(None, list(wurzel.befunde)), [wurzel.anzeige], [d.anzeige for d in satz.dateien if d is not wurzel])

    b = _Buendler(satz, wurzel)
    b.befunde.extend(wurzel.befunde)
    try:
        spec = b.kopie(wurzel.roh, wurzel, ())
    except _ZuGross:
        fehler = Befund(FEHLER, "Bündeln", f"Beim Zusammensetzen entstehen über {MAX_KNOTEN:,} Knoten (Dateien setzen sich gegenseitig vielfach ein).")
        return Buendel(Ergebnis(None, b.befunde + [fehler]), [d.anzeige for d in b.verwendet])
    except RecursionError:
        fehler = Befund(FEHLER, "Bündeln", "Die Verschachtelung der Dateien ist zu tief.")
        return Buendel(Ergebnis(None, b.befunde + [fehler]), [d.anzeige for d in b.verwendet])

    for abschnitt, name, inhalt in b.abgelegt:
        if b.v2:
            ablage = spec.get(abschnitt)
            if not isinstance(ablage, dict):
                ablage = spec[abschnitt] = {}
        else:
            komp = spec.get("components")
            if not isinstance(komp, dict):
                komp = spec["components"] = {}
            ablage = komp.get(abschnitt)
            if not isinstance(ablage, dict):
                ablage = komp[abschnitt] = {}
        ablage[name] = inhalt

    try:
        spec = json.loads(oa_parse._zu_json(spec))  # Größe prüfen und von gemeinsamen Teilobjekten lösen
    except (ValueError, TypeError) as exc:
        return Buendel(Ergebnis(None, b.befunde + [Befund(FEHLER, "Bündeln", str(exc))]), [d.anzeige for d in b.verwendet])

    befunde = b.befunde + oa_parse.pruefen(spec, externe_melden=False)
    verwendet = [d.anzeige for d in b.verwendet]
    unbenutzt = [d.anzeige for d in satz.dateien if d not in b.verwendet]
    return Buendel(Ergebnis(spec, befunde), verwendet, unbenutzt)
