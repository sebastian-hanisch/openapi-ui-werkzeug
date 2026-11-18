"""Texte „Benutzung“ und „Datenschutz“ des Werkzeugs (ohne Streamlit).

Die Zahlen in den Texten stammen aus den Konstanten des Codes und aus ``.streamlit/config.toml``, damit Text und Verhalten nicht
auseinanderlaufen (``tests/test_hinweise.py`` prüft das). Die Texte sind Markdown für ``st.markdown``; Verweise wie ``$ref`` stehen
in Code-Schreibweise, sonst deutet Streamlit das Dollarzeichen als Formel.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import oa_bundle
import oa_render

ORDNER = Path(__file__).resolve().parent
# Zwischenspeicher (st.cache_data) für gelesene Dateien und gebündelte Spezifikationen
CACHE_TTL_SEKUNDEN = 600
CACHE_MAX_LADEN = 8
CACHE_MAX_BUENDELN = 16


def upload_grenze_mb() -> int:
    """Höchstgröße je hochgeladener Datei in MB (``server.maxUploadSize`` in ``.streamlit/config.toml``)."""
    with open(ORDNER / ".streamlit" / "config.toml", "rb") as f:
        return int(tomllib.load(f)["server"]["maxUploadSize"])


def _mb(byte: int) -> str:
    return f"{byte / 1_000_000:g} MB"


def benutzung() -> str:
    return f"""
**1. Dateien hochladen** (Seitenleiste „📥 Dateien“)

* Erlaubt sind `.yaml`, `.yml`, `.json` und `.zip`, je hochgeladener Datei höchstens {upload_grenze_mb()} MB.
* **Beschreibung in einer Datei:** diese Datei hochladen.
* **Beschreibung auf mehrere Dateien verteilt** (`$ref: ./schemas/Sendung.yaml`): den **ganzen Ordner als ZIP** hochladen, dann bleibt die
  Ordnerstruktur erhalten. Alternativ alle Dateien auf einmal markieren; dann gibt es keine Ordnerstruktur, und zwei gleich heißende
  Dateien aus verschiedenen Ordnern lassen sich nicht unterscheiden.
* Aus einem ZIP werden höchstens {oa_bundle.MAX_DATEIEN} Dateien gelesen (entpackt höchstens {_mb(oa_bundle.MAX_ENTPACKT_BYTES)}, je Datei höchstens
  {_mb(oa_bundle.MAX_EINZEL_BYTES)}). Andere Dateitypen, versteckte Dateien und `__MACOSX` werden übersprungen.

**2. Einstiegsdatei wählen**

* Der Einstieg ist die Datei, mit der die Beschreibung beginnt (`openapi:` bzw. `swagger:` auf oberster Ebene). Alle Dateien, auf die sie per `$ref`
  verweist, werden zu einer Spezifikation gebündelt.
* Gibt es mehrere Einstiege (ein Ordner mit mehreren Diensten), steht in der Auswahl je Datei, wie viele Pfade sie hat und wie viele Dateien sie einbindet.
  Vorausgewählt ist die größte Beschreibung, die keine andere Datei einbindet.
* Dateien ohne Pfade und Webhooks („nur Bausteine“) sind ausgeblendet. Der Schalter unter der Auswahl holt sie zurück.

**3. Prüfung lesen**

* **Fehler** stehen zuerst. Sie bedeuten, dass die Oberfläche an der Stelle nicht stimmt, etwa eine fehlende Pflichtangabe oder ein `$ref` auf eine Datei, die nicht
  hochgeladen wurde. Die Oberfläche wird trotzdem gezeichnet, sobald sich die Einstiegsdatei lesen ließ.
* **Warnungen** sind Hinweise, zum Beispiel eine doppelte `operationId` oder ein Verweis auf eine Adresse im Netz.
* Die Prüfung ist kein vollständiger Validator gegen das offizielle Schema der OpenAPI-Spezifikation.

**4. Oberfläche benutzen** (Rahmen unter der Prüfung)

* Eine Operation anklicken, um Parameter, Anfragekörper und Antworten zu sehen. Der Reiter „Schema“ zeigt die Typen statt eines Beispiels.
* Die Filterleiste sucht nach Gruppen (Tags). Seitenleiste „⚙️ Darstellung“: Aufklappen, **Typen aufklappen bis Tiefe** (wie weit verschachtelte Typen
  von selbst offen sind), Höhe des Rahmens.
* **„Try it out“** ist ausgeschaltet. Eingeschaltet schickt die Oberfläche **echte Anfragen** aus Ihrem Browser an die Server aus der Spezifikation
  (nur sinnvoll, wenn Sie dort schreiben dürfen und der Server Zugriffe von anderen Adressen erlaubt).

**5. Laden und Nachlesen**

* „⬇️ Als eigenständige HTML-Datei laden“ speichert die Oberfläche als eine Datei. Beim Öffnen braucht sie Internet (siehe Datenschutz).
* Die Expander darunter zeigen die Endpunktübersicht als Tabelle und die gebündelte Spezifikation als JSON.

**Wenn etwas nicht klappt**

* **Rahmen bleibt leer:** Die Oberfläche kommt von {oa_render.CDN.split("/npm/")[0].replace("https://", "")}; ohne Internetzugang oder bei gesperrtem CDN bleibt der Rahmen leer.
* **„Failed to fetch“ in der Oberfläche:** Eine Stelle verweist auf eine Adresse im Netz, die der Browser nicht laden konnte (kein Internet oder der Server erlaubt es nicht).
* **„… ist nicht hochgeladen“:** Eine verwiesene Datei fehlt. Den ganzen Ordner als ZIP hochladen.
* **„… ist nicht eindeutig“:** Mehrere hochgeladene Dateien passen auf einen Verweis. Als ZIP hochladen, dann gilt die Ordnerstruktur.
* **„… nicht UTF-8-kodiert“:** Die Datei als UTF-8 speichern.
"""


def datenschutz() -> str:
    minuten = CACHE_TTL_SEKUNDEN // 60
    return f"""
Dies ist ein Hinweis zur Funktionsweise dieser App, keine vollständige Datenschutzerklärung eines Betreibers.

**Hochgeladene Dateien**

* Der Server, auf dem die App ausgeführt wird, liest, prüft und bündelt die Dateien im Arbeitsspeicher. Die App schreibt sie nicht auf die Festplatte, in Protokolle
  oder Datenbanken und sendet sie nicht weiter.
* **Zwischenspeicher:** Zur Beschleunigung hält die App den Inhalt der Dateien und das Ergebnis im Zwischenspeicher des Servers (höchstens {CACHE_MAX_LADEN} bzw.
  {CACHE_MAX_BUENDELN} Einträge). Ein Eintrag verfällt nach {minuten} Minuten oder wenn der Platz gebraucht wird, und beim Neustart der App ist alles weg. Der
  Zwischenspeicher gilt für alle Sitzungen derselben App-Instanz; die App bietet aber keine Möglichkeit, Einträge anderer Sitzungen anzusehen.

**Verbindungen Ihres Browsers zu Dritten**

* **Swagger UI:** Die Oberfläche lädt beim Anzeigen ihre Programmdateien vom CDN jsDelivr ({oa_render.CDN.split("/npm/")[0].replace("https://", "")}). Dabei erfährt jsDelivr technisch bedingt Ihre
  IP-Adresse und die üblichen Verbindungsdaten Ihres Browsers. Der Inhalt Ihrer Dateien wird dabei nicht übertragen. Ohne diese Verbindung bleibt der Rahmen leer.
* **Verweise auf Netzadressen** (`https://…` in `$ref`): Der Browser lädt sie, wenn er kann. Der Betreiber dieser Adresse sieht die Anfrage.
* **„Try it out“** (nur wenn eingeschaltet): Ihr Browser sendet echte Anfragen an die Server aus der Spezifikation, mit den Werten, die Sie dort eintragen.
* Die Oberfläche läuft in einem abgeschotteten Rahmen ohne Zugriff auf die App oder auf andere hochgeladene Dateien.

**Heruntergeladene HTML-Datei**

* Sie enthält die gesamte Spezifikation im Klartext (mit allen Beispielen, Server-Adressen und allem, was in Ihren Dateien steht) und lädt beim Öffnen ebenfalls von jsDelivr.

**Statistik und Plattform**

* In der Konfiguration dieses Repos ist die Nutzungsstatistik von Streamlit ausgeschaltet (`gatherUsageStats = false`). Die App legt keine Konten an und setzt selbst keine
  Cookies; Streamlit verwendet für die Sitzung und den Schutz beim Hochladen eigene technische Mechanismen.
* Wird die App auf einer Plattform betrieben (zum Beispiel Streamlit Community Cloud), gelten zusätzlich deren Datenschutzhinweise und Protokolle (etwa Zugriffsdaten).

**Empfehlung**

* Laden Sie keine Dateien mit Zugangsdaten, Tokens oder vertraulichen Inhalten hoch, wenn Sie die App nicht selbst betreiben oder dem Betreiber nicht vertrauen.
"""
