"""Aus einer Spezifikation eine eigenständige HTML-Seite mit der Swagger UI bauen (ohne Streamlit).

Die Seite lädt ``swagger-ui-dist`` in einer festen Version vom CDN jsDelivr. Die Spezifikation steht als JSON-Text in der
Seite; sie wird so geschrieben, dass sie das umgebende ``<script>`` nicht beenden kann.
"""
from __future__ import annotations

import base64
import html
import json
import re

SWAGGER_UI_VERSION = "5.17.14"
CDN = f"https://cdn.jsdelivr.net/npm/swagger-ui-dist@{SWAGGER_UI_VERSION}"
DOC_EXPANSION = ("list", "full", "none")
# Wie tief die Swagger UI verschachtelte Typen von sich aus aufklappt. Die Standardtiefe 1 der Swagger UI zeigt eine Eigenschaft, deren Typ
# selbst ein benanntes Schema ist (`LocationType`, `UUIDType` …), nur als zugeklappten Block `LocationType[...]`; nur ein unmittelbar
# eingetragenes `integer` steht gleich da. Bei Tiefe 3 steht auch dort `string($uuid)`, `integer($int64)` oder die Liste der erlaubten Werte.
TYP_TIEFE_MIN, TYP_TIEFE_MAX, TYP_TIEFE_STANDARD = 1, 6, 3
# Feste Basisadresse der Spezifikation. Die Swagger UI löst die ``$ref`` einer Operation oder eines Schemas erst beim Aufklappen auf,
# und zwar gegen die Adresse des Dokuments. Eine Seite in einem Rahmen mit ``data:``-Adresse hat keine brauchbare (die Adresse
# ist die ganze Seite in Base64): die Oberfläche zeigt dann bei jedem Aufklappen nur einen endlos drehenden Ladekreis. ``.invalid``
# ist nach RFC 2606 reserviert und wird nie aufgelöst; geladen wird die Adresse nicht (die Spezifikation steht schon in der Seite).
BASIS_ADRESSE = "https://openapi.invalid/openapi.json"
STANDARD_METHODEN = ["get", "put", "post", "delete", "options", "head", "patch", "trace"]


def json_fuer_script(wert: object) -> str:
    """JSON, das sicher in einem ``<script>``-Block steht: kein ``<``, ``>``, ``&`` und keine Zeilentrenner U+2028/2029."""
    text = json.dumps(wert, ensure_ascii=False)
    for zeichen, ersatz in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"), (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(zeichen, ersatz)
    return text


def html_seite(
    spec: dict,
    *,
    titel: str = "API-Dokumentation",
    doc_expansion: str = "list",
    filter_leiste: bool = True,
    try_it_out: bool = False,
    typ_tiefe: int = TYP_TIEFE_STANDARD,
) -> str:
    """Vollständige HTML-Seite. ``try_it_out=False`` schaltet das Senden von Anfragen ab (leere Methodenliste).

    ``typ_tiefe``: bis zu welcher Verschachtelungstiefe Typen in der Schema-Liste und in der Schema-Ansicht der Operationen
    aufgeklappt erscheinen (``TYP_TIEFE_MIN`` bis ``TYP_TIEFE_MAX``; 1 ist der Standard der Swagger UI).
    """
    if doc_expansion not in DOC_EXPANSION:
        raise ValueError(f"doc_expansion muss eine von {DOC_EXPANSION} sein, nicht {doc_expansion!r}")
    if isinstance(typ_tiefe, bool) or not isinstance(typ_tiefe, int) or not TYP_TIEFE_MIN <= typ_tiefe <= TYP_TIEFE_MAX:
        raise ValueError(f"typ_tiefe muss eine ganze Zahl von {TYP_TIEFE_MIN} bis {TYP_TIEFE_MAX} sein, nicht {typ_tiefe!r}")
    konfig = {
        "spec": spec,
        "dom_id": "#swagger-ui",
        "deepLinking": False,
        "docExpansion": doc_expansion,
        "filter": bool(filter_leiste),
        "supportedSubmitMethods": STANDARD_METHODEN if try_it_out else [],
        "defaultModelsExpandDepth": typ_tiefe,
        "defaultModelExpandDepth": typ_tiefe,
        "tryItOutEnabled": False,
    }
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titel)}</title>
<link rel="stylesheet" href="{CDN}/swagger-ui.css">
<style>
  html {{ box-sizing: border-box; }}
  *, *:before, *:after {{ box-sizing: inherit; }}
  body {{ margin: 0; background: #ffffff; }}
  .swagger-ui .topbar {{ display: none; }}
  .swagger-ui .info a.link {{ display: none; }}  /* die Basisadresse (siehe BASIS_ADRESSE) ist keine echte Adresse, nicht anzeigen */
</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="{CDN}/swagger-ui-bundle.js"></script>
<script>
  window.onload = function () {{
    var konfig = {json_fuer_script(konfig)};
    konfig.presets = [SwaggerUIBundle.presets.apis];
    konfig.layout = "BaseLayout";
    window.ui = SwaggerUIBundle(konfig);
    window.ui.specActions.updateUrl({json.dumps(BASIS_ADRESSE)});
  }};
</script>
</body>
</html>
"""


def html_dateiname(spec: dict) -> str:
    """Dateiname für den Download: Titel der API als Kleinbuchstaben-Kurzform, sonst ``openapi.html``."""
    info = spec.get("info")
    titel = str(info.get("title", "")) if isinstance(info, dict) else ""
    for umlaut, ersatz in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        titel = titel.lower().replace(umlaut, ersatz)
    slug = re.sub(r"[^a-z0-9]+", "-", titel).strip("-")
    return f"{slug or 'openapi'}.html"


def als_data_url(seite: str) -> str:
    """``data:``-Adresse der Seite. Ein Rahmen mit dieser Adresse hat eine eigene, leere Herkunft: kein Zugriff auf die App."""
    return "data:text/html;charset=utf-8;base64," + base64.b64encode(seite.encode("utf-8")).decode("ascii")
