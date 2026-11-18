"""OpenAPI-YAML → Swagger UI (Werkzeug): eigene Dateien hochladen, prüfen, als Oberfläche anzeigen und als HTML-Datei laden."""
from __future__ import annotations

import json

import streamlit as st

import oa_bundle
import oa_hinweise
import oa_parse
import oa_render

DOC_EXPANSION_TEXT = {
    "list": "Operationen einer Gruppe sichtbar, Details zugeklappt",
    "full": "Alles aufgeklappt",
    "none": "Alles zugeklappt",
}
HOEHE_MIN, HOEHE_MAX, HOEHE_STANDARD = 400, 2000, 900
BEFUND_SPALTEN = {
    "Stufe": st.column_config.TextColumn(width="small"),
    "Ort": st.column_config.TextColumn(width="medium"),
    "Meldung": st.column_config.TextColumn(width="large"),
}

st.set_page_config(page_title="OpenAPI-Werkzeug – Sebastian Hanisch", layout="wide")

st.title("🛠️ OpenAPI-Datei als Oberfläche")
st.markdown(
    """
Laden Sie eine **OpenAPI-Beschreibung** hoch (OpenAPI 3.0, 3.1 und Swagger 2.0), und Sie bekommen die **Swagger UI** dazu:
Endpunkte nach Gruppen, Parameter, Schemas und Beispiele. Die Beschreibung darf **auf mehrere Dateien verteilt** sein
(`$ref: ./schemas/Sendung.yaml`): Laden Sie dann den **Ordner als ZIP** hoch, oder markieren Sie alle Dateien auf einmal.
Die Dateien werden zu einer Spezifikation **gebündelt** und **geprüft** (Pflichtfelder, `$ref`-Verweise, doppelte `operationId`,
Pfadparameter). Die fertige Seite lässt sich als **eigenständige HTML-Datei** laden. Die Dateien werden im Arbeitsspeicher verarbeitet und nicht
dauerhaft gespeichert; was dabei nach außen geht, steht unter „Datenschutz“.
"""
)

with st.expander("📖 Benutzung"):
    st.markdown(oa_hinweise.benutzung())
with st.expander("🔒 Datenschutz"):
    st.markdown(oa_hinweise.datenschutz())


# Zwischenspeicher mit Ablaufzeit: hochgeladene Inhalte bleiben nicht unbegrenzt im Speicher des Servers (siehe Datenschutz)
@st.cache_data(show_spinner=False, max_entries=oa_hinweise.CACHE_MAX_LADEN, ttl=oa_hinweise.CACHE_TTL_SEKUNDEN)
def _laden(uploads: tuple[tuple[str, bytes], ...]) -> oa_bundle.Satz:
    return oa_bundle.laden(uploads)


@st.cache_data(show_spinner=False, max_entries=oa_hinweise.CACHE_MAX_BUENDELN, ttl=oa_hinweise.CACHE_TTL_SEKUNDEN)
def _buendeln(uploads: tuple[tuple[str, bytes], ...], wurzel: str) -> oa_bundle.Buendel:
    return oa_bundle.buendeln(_laden(uploads), wurzel)


def _befund_zeilen(befunde: list[oa_parse.Befund]) -> list[dict[str, str]]:
    """Fehler vor Warnungen, sonst in der Reihenfolge des Fundes."""
    ordnung = sorted(befunde, key=lambda b: b.stufe != oa_parse.FEHLER)
    return [{"Stufe": b.stufe, "Ort": b.ort, "Meldung": b.text} for b in ordnung]


with st.sidebar:
    st.header("📥 Dateien")
    dateien = st.file_uploader(
        "OpenAPI-Dateien",
        type=["yaml", "yml", "json", "zip"],
        accept_multiple_files=True,
        key="dateien",
        label_visibility="collapsed",
        help=(
            "`.yaml`, `.yml`, `.json` oder ein ZIP mit dem ganzen Ordner (die Ordnerstruktur bleibt erhalten). Mehrere Dateien "
            "bilden zusammen eine Beschreibung: die Datei mit `openapi:` bzw. `swagger:` ist der Einstieg, die anderen werden über "
            "`$ref` eingebunden. Gibt es mehrere Einstiegsdateien, wählen Sie unten eine aus."
        ),
    )
    uploads = tuple((d.name, d.getvalue()) for d in dateien)
    satz = _laden(uploads) if uploads else oa_bundle.Satz()
    auswahl = st.container()  # steht über dem Schalter, wird aber erst danach gefüllt (hängt von ihm ab)
    _, ausgeblendet = satz.angebot(False)
    auch_bausteine = False
    if ausgeblendet:
        auch_bausteine = st.checkbox(
            f"Auch Dateien ohne Pfade anbieten ({len(ausgeblendet)} ausgeblendet)",
            value=False,
            key="bausteine_zeigen",
            help=(
                "Dateien mit `openapi:`-Kopf, aber ohne `paths` und `webhooks`, sind gemeinsame Bausteine, die andere Dateien einbinden. "
                "Sie ergeben allein keine Oberfläche mit Endpunkten und stehen deshalb nicht zur Wahl."
            ),
        )
    einstiege, _ = satz.angebot(auch_bausteine)
    kandidaten = [e.datei for e in einstiege]
    gewaehlt = 0
    if "gewaehlt" in st.session_state and st.session_state["gewaehlt"] >= len(kandidaten):  # die Liste wurde kürzer (Schalter aus, andere Dateien)
        del st.session_state["gewaehlt"]
    if len(kandidaten) > 1:
        gewaehlt = auswahl.selectbox(
            "Einstiegsdatei",
            range(len(kandidaten)),
            format_func=lambda i: f"{i + 1}. {einstiege[i].beschriftung}",
            key="gewaehlt",
            help=(
                "Eine Datei zählt als Einstieg, wenn sie `openapi:` oder `swagger:` enthält. Die Reihenfolge kommt aus den `$ref`-Verweisen: "
                "Beschreibungen mit Pfaden, die keine andere Datei einbindet, stehen vorn. „Nur Bausteine“ und „selbst eingebunden“ sind "
                "gemeinsame Teile, die andere Dateien einbinden."
            ),
        )
        freie = [e for e in einstiege if e.ist_freie_beschreibung]
        if len(freie) == 1:
            auswahl.caption("Vorausgewählt: die einzige Datei mit Pfaden, die keine andere Datei einbindet.")
        elif freie:
            auswahl.caption(
                f"Vorausgewählt: die größte von {len(freie)} Beschreibungen, die keine andere Datei einbindet. "
                "Die anderen sind eigene Einstiege; wählen Sie bei Bedarf eine davon."
            )

    st.header("⚙️ Darstellung")
    doc_expansion = st.selectbox(
        "Aufklappen",
        list(DOC_EXPANSION_TEXT),
        format_func=DOC_EXPANSION_TEXT.get,
        key="doc_expansion",
    )
    filter_leiste = st.checkbox("Filterleiste anzeigen", value=True, key="filter_leiste")
    typ_tiefe = st.slider(
        "Typen aufklappen bis Tiefe",
        oa_render.TYP_TIEFE_MIN,
        oa_render.TYP_TIEFE_MAX,
        oa_render.TYP_TIEFE_STANDARD,
        key="typ_tiefe",
        help=(
            "Wie tief verschachtelte Typen in der Schema-Liste und in der Schema-Ansicht der Operationen von selbst aufgeklappt sind. "
            "Bei 1 erscheint ein Typ, der selbst ein benanntes Schema ist (z. B. `UUIDType`), nur als zugeklappter Block."
        ),
    )
    try_it_out = st.checkbox(
        "„Try it out“ erlauben",
        value=False,
        key="try_it_out",
        help=(
            "Schickt Anfragen aus Ihrem Browser an die Server aus der Spezifikation. Das klappt nur, wenn der Server "
            "Zugriffe von anderen Adressen erlaubt (CORS). Aus: die Oberfläche zeigt nur an."
        ),
    )
    hoehe = st.slider("Höhe der Ansicht (px)", HOEHE_MIN, HOEHE_MAX, HOEHE_STANDARD, step=50, key="hoehe")

if not dateien:
    st.info("Laden Sie links eine OpenAPI-Datei hoch. Die Oberfläche erscheint hier.")
    st.stop()

if satz.befunde:  # Probleme beim Auspacken (ZIP)
    st.error("Beim Lesen der hochgeladenen Dateien gab es Fehler:")
    st.dataframe(_befund_zeilen(satz.befunde), hide_index=True, width="stretch", column_config=BEFUND_SPALTEN)
if not kandidaten:
    st.error("Es wurde keine lesbare Datei gefunden (erwartet: `.yaml`, `.yml`, `.json` oder ein ZIP damit).")
    st.stop()

einstieg = kandidaten[gewaehlt]
buendel = _buendeln(uploads, einstieg.pfad)
erg = buendel.ergebnis
if erg.fehler:
    st.error(
        f"{einstieg.anzeige}: {len(erg.fehler)} Fehler. "
        + ("Die Oberfläche wird trotzdem gezeichnet." if erg.spec else "Eine Oberfläche ist so nicht möglich.")
    )
if erg.spec is None:
    st.dataframe(_befund_zeilen(erg.befunde), hide_index=True, width="stretch", column_config=BEFUND_SPALTEN)
    st.stop()

spec = erg.spec
kz = oa_parse.kennzahlen(spec)
st.subheader(kz["titel"] or "(ohne Titel)")
spalten = st.columns(5)
spalten[0].metric("Version", kz["version"])
spalten[1].metric("Operationen", kz["operationen"])
spalten[2].metric("Pfade", kz["pfade"])
spalten[3].metric("Gruppen (Tags)", kz["tags"])
spalten[4].metric("Schemas", kz["schemas"])

if len(buendel.verwendet) > 1 or buendel.unbenutzt:
    with st.expander(
        f"📁 Dateien: {len(buendel.verwendet)} zu einer Spezifikation gebündelt"
        + (f", {len(buendel.unbenutzt)} nicht verwendet" if buendel.unbenutzt else "")
    ):
        st.markdown("**Verwendet** (von der Einstiegsdatei aus über `$ref` erreicht):")
        st.markdown("\n".join(f"* `{n}`" for n in buendel.verwendet))
        if buendel.unbenutzt:
            st.markdown("**Nicht verwendet** (hochgeladen, aber von der Einstiegsdatei aus nicht erreicht):")
            st.markdown("\n".join(f"* `{n}`" for n in buendel.unbenutzt))

if erg.befunde:
    with st.expander(f"🔎 Prüfung: {len(erg.fehler)} Fehler, {len(erg.warnungen)} Warnungen", expanded=bool(erg.fehler)):
        st.dataframe(_befund_zeilen(erg.befunde), hide_index=True, width="stretch", column_config=BEFUND_SPALTEN)
else:
    st.success("Prüfung: keine Fehler und keine Warnungen gefunden.")

seite = oa_render.html_seite(
    spec,
    titel=kz["titel"] or "API-Dokumentation",
    doc_expansion=doc_expansion,
    filter_leiste=filter_leiste,
    try_it_out=try_it_out,
    typ_tiefe=typ_tiefe,
)
st.iframe(oa_render.als_data_url(seite), height=hoehe)
st.caption(
    f"Die Oberfläche lädt Swagger UI {oa_render.SWAGGER_UI_VERSION} vom CDN jsDelivr; ohne Internetzugang bleibt der Rahmen leer. "
    "Sie läuft in einem abgeschotteten Rahmen ohne Zugriff auf diese App."
)
st.download_button(
    "⬇️ Als eigenständige HTML-Datei laden",
    data=seite,
    file_name=oa_render.html_dateiname(spec),
    mime="text/html",
    key="download_html",
)

with st.expander("📋 Endpunktübersicht"):
    ops = oa_parse.operationen(spec)
    if ops:
        st.dataframe(
            [
                {
                    "Methode": o.methode,
                    "Pfad": o.pfad,
                    "Zusammenfassung": o.zusammenfassung,
                    "Tags": ", ".join(o.tags),
                    "operationId": o.operation_id,
                    "veraltet": "ja" if o.veraltet else "",
                }
                for o in ops
            ],
            hide_index=True,
            width="stretch",
        )
    else:
        st.info("Die Spezifikation beschreibt keine Operationen unter `paths`.")

with st.expander("🧾 Gelesene Spezifikation als JSON"):
    st.caption(
        "So kommt die Datei in der Oberfläche an: YAML-Anker und -Aliase sind aufgelöst, `true`/`false` sind die einzigen Wahrheitswerte, "
        "Datumsangaben bleiben Text."
    )
    st.code(json.dumps(spec, ensure_ascii=False, indent=2), language="json")
