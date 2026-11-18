# OpenAPI-Datei als Oberfläche (Werkzeug)

Werkzeug: **eigene OpenAPI-Beschreibungen hochladen** (`.yaml`, `.yml`, `.json` oder ein **ZIP mit dem ganzen Ordner**; OpenAPI 3.0, 3.1
und Swagger 2.0) und als **Swagger UI** ansehen. Eine Beschreibung darf auf mehrere Dateien verteilt sein (`$ref: ./schemas/Sendung.yaml`):
die Dateien werden zu einer Spezifikation **gebündelt**. Vorher wird alles geprüft, und die fertige Seite lässt sich als
**eigenständige HTML-Datei** laden. Das Werkzeug hat **keine Beispiele** und keine Texteingabe; die Variante mit mitgelieferten
Beispielen für die Webseite ist `openapi-ui-demo` (nur eine Datei je Beispiel).

Stand: 2026-11-18 lokal gebaut, die App im Browser mit hochgeladenen Dateien geprüft; **nicht** in der Streamlit Community Cloud deployt oder dort geprüft.

## Starten

```bash
python -m venv venv
venv/Scripts/python.exe -m pip install -r requirements-dev.txt
venv/Scripts/python.exe -m streamlit run app.py
```

Die App lädt die Swagger UI (Version 5.17.14) zur Laufzeit vom CDN jsDelivr. Ohne Internetzugang bleibt der Rahmen mit der
Oberfläche leer; Prüfung, Kennzahlen, Endpunktübersicht und JSON-Ansicht funktionieren weiter.

## Was das Werkzeug tut

1. **Hochladen** (Seitenleiste): eine Datei, mehrere Dateien auf einmal oder ein ZIP (auch mehrere ZIPs). Alles Hochgeladene bildet **eine
   Dateimenge**. Einstiegsdatei ist eine Datei mit `openapi:` bzw. `swagger:` auf oberster Ebene; die übrigen Dateien stehen allen zur
   Verfügung. Dateien werden nur für die Sitzung gelesen und nicht gespeichert. Höchstgröße je Upload: 5 MB (`.streamlit/config.toml`).
   **Die Vorauswahl der Einstiegsdatei ergibt sich aus der Struktur** (`Satz.einstiege()`, ohne Namensraten und ohne Sprachmodell): Aus den
   `$ref`-Verweisen aller Dateien entsteht ein Graph. Ein Einstieg beschreibt Pfade oder Webhooks und wird **von keiner anderen Datei eingebunden**;
   gemeinsame Bausteine werden irgendwo eingebunden, auch wenn sie einen `openapi:`-Kopf und Pfade haben, oder sie haben `paths: {}`.
   Reihenfolge: freie Beschreibungen, dann eingebundene („selbst eingebunden“), dann Dateien ohne Pfade („nur Bausteine“); darin mehr Pfade zuerst,
   dann mehr erreichte Dateien (auch mittelbar über `$ref`), sonst die Reihenfolge des Hochladens. Die Auswahl („1. name.yaml (12 Pfade, bindet 30
   Dateien ein)“) zeigt das, die App nennt die Begründung. **Dateien ohne Pfade und Webhooks („nur Bausteine“) stehen nicht zur Wahl**, sobald es
   mindestens eine Beschreibung mit Pfaden oder Webhooks gibt; sie sind ausgeblendet und per Schalter „Auch Dateien ohne Pfade anbieten (n ausgeblendet)“
   wieder wählbar. Gibt es nur Bausteine (etwa nur eine Komponentendatei), bleiben sie sichtbar. **Gibt es mehrere freie Beschreibungen** (ein Ordner mit mehreren Diensten), gibt es keine
   eindeutige „richtige“; dann ist die größte vorgewählt und die anderen stehen zur Wahl.
2. **Bündeln** (`oa_bundle.py`): `$ref` auf andere Dateien werden aufgelöst, weil die Oberfläche im Rahmen nur diese eine Seite bekommt.
   * Alles unter `components/<Abschnitt>/<Name>` (bei Swagger 2.0 `definitions`, `parameters`, `responses`) wandert in `components` der
     Einstiegsdatei und **behält seinen Namen**; so zeigt die Oberfläche weiter „Sendung“ statt eines eingesetzten Blocks, und rekursive Schemas
     (ein Knoten verweist auf sich selbst) funktionieren. Steht in der Einstiegsdatei schon `Sendung: {$ref: ./schemas/Sendung.yaml}`, gilt dieser Name.
   * Eine ganze Datei an einer Schema-Stelle (`schema`, `items`, `properties`, `allOf` …) wird als Schema abgelegt und nach der Datei benannt.
   * Alles andere, etwa ein Pfadeintrag in `paths/sendungen.yaml`, wird an Ort und Stelle eingesetzt.
   * Ein `$ref` in einer fremden Datei, der mit `#` beginnt, gilt für diese Datei (wie in der Spezifikation vorgesehen).
   * Die Pfade der Verweise gelten ab der Datei, in der sie stehen (`../common.yaml`). Ohne Ordnerstruktur (Dateien einzeln hochgeladen) wird
     die Datei über das Ende des Pfades und dann über den Dateinamen gesucht, solange das eindeutig ist.
3. **Prüfen** (Fehler und Warnungen, Fehler zuerst), an der gebündelten Spezifikation: Version (`openapi: 3.x` bzw. `swagger: "2.0"`),
   `info.title`, `info.version`, `paths` (bei 3.1 genügen `webhooks` oder `components`), Pfad beginnt mit `/`, `responses` je Operation,
   doppelte `operationId`, Pfadparameter `{x}` ohne Beschreibung, `$ref` auf nichts, `$ref` auf eine **nicht hochgeladene oder nicht lesbare Datei**
   oder auf eine nicht eindeutige (Fehler, mit Dateiname und Fundort), `$ref` auf eine Adresse im Netz (Warnung, wird nicht geladen), doppelte
   YAML-Schlüssel mit Datei und Zeilennummer. Fremde Dateien müssen keine vollständige Beschreibung sein (ein Schema allein ist in Ordnung).
   Ist die Einstiegsdatei nicht lesbar (YAML-Fehler mit Zeile und Spalte, leer, keine UTF-8-Kodierung, zu groß), steht der Fehler statt der Oberfläche da.
4. **Zeichnen:** Swagger UI in einem Rahmen mit `data:`-Adresse. Bei Fehlern in der Spezifikation wird trotzdem gezeichnet, solange sich die Einstiegsdatei lesen ließ.
5. **Laden:** die Seite als eigenständige HTML-Datei (`<Titel>.html`), ohne Verweise auf weitere Dateien.
6. **Nachlesen:** welche Dateien verwendet und welche nicht erreicht wurden (nur sichtbar bei mehreren Dateien), Kennzahlen, Endpunktübersicht und die
   gebündelte Spezifikation als JSON.

Darstellung (Seitenleiste): Aufklappen (`list`, `full`, `none`), Filterleiste, Typen aufklappen bis Tiefe (1 bis 6, Standard 3: wie tief verschachtelte Typen, die selbst benannte Schemas sind, von selbst aufgeklappt erscheinen; die Standardtiefe 1 der Swagger UI zeigt sie nur als zugeklappten Block `UUIDType[...]`, die Typdetails stünden dann erst nach dem Aufklappen da), „Try it out“ (Standard: aus), Höhe des Rahmens (400 bis 2000 px).

## Grenzen und Annahmen

* **Die Prüfung ist kein vollständiger Validator.** Sie fängt die Fehler, die eine Oberfläche sichtbar kaputt machen. Ob eine Datei dem
  offiziellen JSON-Schema der OpenAPI-Spezifikation entspricht, sagt sie nicht.
* **Kein Ordner-Upload.** Das Upload-Feld von Streamlit nimmt keine Ordner. Der Ordner geht als ZIP (die Ordnerstruktur bleibt erhalten) oder
  als alle Dateien auf einmal markiert (dann gibt es keine Ordnerstruktur; heißen zwei Dateien in verschiedenen Ordnern gleich und wird eine
  davon über den bloßen Dateinamen verlangt, meldet das Werkzeug „nicht eindeutig“ und empfiehlt das ZIP).
* **Verweise auf Netzadressen** (`https://…`) lädt das Werkzeug nicht (es liest nur, was hochgeladen wurde) und warnt. Die Oberfläche versucht
  sie im Browser aufzulösen; das klappt mit Internetzugang und wenn der Server Zugriffe von anderen Adressen erlaubt (CORS). Am 2026-11-18 mit
  den Schemas von `opensource.zalando.com` geprüft (Antwort mit `Access-Control-Allow-Origin: *`, alle Operationen klappten ohne Fehler auf);
  bei einem Server ohne diese Kopfzeile oder ohne Internet meldet die Oberfläche dort „Failed to fetch“, die übrige Seite bleibt benutzbar.
* **Eingesetzte Teile werden vervielfacht.** Eine Datei, die nicht an einer Schema-Stelle und nicht unter `components` verwiesen wird, steht
  an jeder Verweisstelle vollständig in der gebündelten Spezifikation. Ein Kreis aus solchen Dateien wird an der Stelle, an der er sich schließt, als
  Schema abgelegt.
* **Grenzen:** je Datei höchstens 2.000.000 Zeichen Eingabe; nach dem Auflösen von YAML-Ankern höchstens 6.000.000 Zeichen JSON (fängt verschachtelte
  und zyklische Aliase, „YAML-Bombe“, ab). ZIP: höchstens 300 Dateien, 25 MB entpackt, 8 MB je Datei; ZIP-Einträge mit `..`, absolutem Pfad,
  Namen mit führendem Punkt, `__MACOSX` und alle Dateien außer `.yaml`/`.yml`/`.json` werden übersprungen (es wird nichts auf die Platte geschrieben).
  Gebündelte Spezifikation: höchstens 2.000.000 Knoten, das fängt Dateien ab, die sich gegenseitig vielfach einsetzen.
* **Lesen mit PyYAML (`oa_parse.py`).** Abweichend vom Standard von PyYAML sind nur `true` und `false` Wahrheitswerte, und Datumsangaben bleiben Text.
* **Abgeschotteter Rahmen.** Die Seite steht als `data:`-Adresse im Rahmen. Dessen Herkunft ist von der App getrennt (im Browser an der
  Demo-Schwester geprüft: `contentDocument` des Rahmens ist von der App aus nicht lesbar). Die Spezifikation steht als maskiertes JSON in
  der Seite und kann den Skriptblock nicht beenden. Eine Datei aus fremder Quelle kann die App also nicht auslesen.
* **Feste Basisadresse (`oa_render.BASIS_ADRESSE`).** Die Swagger UI löst die `$ref` einer Operation oder eines Schemas erst beim Aufklappen auf,
  und zwar gegen die Adresse des Dokuments. Im `data:`-Rahmen ist die Adresse die ganze Seite in Base64: Ohne Korrektur drehte sich beim Aufklappen
  jeder Operation ein endloser Ladekreis (Methoden- und Typdetails fehlten alle; das fiel zunächst nicht auf, weil nur die zugeklappte Oberfläche
  angesehen worden war). Die Seite setzt deshalb nach dem Start eine feste Adresse mit der reservierten Endung `.invalid`
  (`specActions.updateUrl`), die nie geladen wird; ein Stil blendet den Link aus, den die Swagger UI daraus unter dem Titel macht. Im Browser mit
  echten Dateien geprüft; die Python-Tests sichern nur, dass die Zeilen in der Seite stehen. Die Version der Swagger UI ist festgelegt
  (5.17.14); bei einer neuen Version diese Stelle im Browser erneut prüfen.
* **„Try it out“** schickt Anfragen aus dem Browser der Nutzerin oder des Nutzers an die Server aus der Spezifikation, nur wenn der Haken
  gesetzt ist; der Server muss Zugriffe von anderen Adressen erlauben (CORS). Das Senden selbst ist nicht getestet, nur dass der Schalter
  die Konfiguration der Swagger UI ändert.
* **Nicht geprüft:** Verhalten in der Streamlit Community Cloud (ob die dortige Seite den `data:`-Rahmen zulässt), dunkles Design,
  Upload mit dem Datei-Dialog des Browsers (im Browser wurde die Datei per Skript in das Feld gelegt; AppTest lädt über die Testschnittstelle hoch).
  **Das Bündeln und die Einstiegswahl sind an selbst geschriebenen Ordnern erprobt** (Beispiel `tests/fixtures/ordner/`, Aufbau wie üblich: Wurzel,
  `paths/`, `schemas/`, gemeinsame Datei) und einmal von Hand an einem echten, tief verschachtelten Ordner mit 48 Dateien und drei Diensten (nicht im
  Repo, weil nicht öffentlich; dort kein Fehler, nur die erwarteten Warnungen). Muster, die ich nicht kenne, können unaufgelöst bleiben; das
  Werkzeug meldet sie dann als Fehler oder Warnung. Die Einstiegswahl ist eine Heuristik: ein Einstieg, der von einer anderen Datei eingebunden wird
  (etwa ein Dienst, der einen anderen als Client verwendet), steht hinter den freien Beschreibungen, bleibt aber wählbar.
* `st.iframe` setzt eine neuere Streamlit-Version voraus (geprüft mit 1.64, deshalb `streamlit>=1.64`).
* **Doppelter Code:** `oa_parse.py` und `oa_render.py` stehen gleich in `openapi-ui-demo` (`oa_bundle.py` gibt es nur hier). Änderungen an einem Ort in beiden nachziehen.

## Dateien

```
app.py                   Oberfläche des Werkzeugs
oa_parse.py              Lesen, Prüfen, Kennzahlen, Bytes → Text (ohne Streamlit)
oa_bundle.py             Dateimenge laden (ZIP auspacken), `$ref` auf andere Dateien auflösen, zu einer Spezifikation bündeln
oa_render.py             HTML-Seite mit Swagger UI, data:-Adresse, Dateiname
tests/                   135 Tests (Parser, Bündeln, Einstiegswahl, Renderer, AppTest mit Upload, Laufzeit-Imports)
tests/fixtures/          vier Testdateien (3.0, 3.1, 2.0, absichtlich fehlerhaft) und `ordner/` (sechs Dateien, 3.0.3), nur für die Tests
requirements.txt         streamlit, pyyaml (ungepinnt)
requirements-dev.txt     dazu pytest
.streamlit/config.toml   Upload-Grenze 5 MB
```

## Tests

```bash
venv/Scripts/python.exe -m pytest tests -q
```

135 Tests; die Laufzeit schwankt mit der Rechnerlast (gemessen: 5 bis 130 Sekunden, die AppTests sind der langsame Teil). Die Kennzahlen der Testdateien sind von Hand aus den Dateien gezählt; die Gegenprobe zum Lesen ist die
Standardbibliothek (`json`). Die Bündel-Tests prüfen am Ordnerbeispiel (als ZIP und als einzelne Dateien dasselbe Ergebnis), dass kein Verweis
auf eine Datei übrig bleibt, jeder Verweis ein Ziel hat, rekursive Schemas und Kreise enden, und die Fehlerfälle (fehlende, nicht lesbare, nicht
eindeutige Datei, Netzadresse, Namensgleichheit, ZIP-Grenzen und unbrauchbare ZIP-Einträge). Die AppTests laden Dateien hoch (eine, mehrere, ein
ZIP, gleich benannte, JSON, unlesbares YAML, falsche Kodierung, leere Datei, einen Ordner mit fehlender Datei) und lesen die Konfiguration der
Swagger UI aus der Adresse des Rahmens. Die Swagger UI selbst (Zeichnen, Aufklappen von Operationen und Schemas) prüft kein Test, nur der Blick im Browser; das Aufklappen im `data:`-Rahmen ist am 2026-11-18 mit einem echten Ordner (48 Dateien, drei Dienste) im Browser nachgeprüft.

## Lizenz

MIT, siehe [LICENSE](LICENSE). Die Swagger UI (Apache-2.0) wird zur Laufzeit vom CDN jsDelivr geladen und ist nicht Teil dieses Repos.
