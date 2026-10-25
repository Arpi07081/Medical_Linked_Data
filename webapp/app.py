"""
app.py — Flask web application for the bilingual medical knowledge graph.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from flask import Flask, Response, flash, redirect, render_template, request, url_for
from rdflib import Graph

WEBAPP_DIR = Path(__file__).resolve().parent
DATA_DIR   = WEBAPP_DIR.parent
sys.path.insert(0, str(DATA_DIR))   # repo root — for namespaces module
sys.path.insert(0, str(WEBAPP_DIR)) # webapp dir — for queries module

import queries

ONTOLOGY_DIR     = DATA_DIR / "ontology"
DEFAULT_GLOSSARY = ONTOLOGY_DIR / "ttl" / "glossary.ttl"
GRAPH_TEMPLATE   = ONTOLOGY_DIR / "graph_template.html"
TEST_GLOSSARY    = WEBAPP_DIR / "active-test-glossary.ttl"

# Prepended to developer SPARQL queries that don't declare their own prefixes
SPARQL_PREFIXES = """
PREFIX ontolex:  <http://www.w3.org/ns/lemon/ontolex#>
PREFIX vartrans: <http://www.w3.org/ns/lemon/vartrans#>
PREFIX lime:     <http://www.w3.org/ns/lemon/lime#>
PREFIX skos:     <http://www.w3.org/2004/02/skos/core#>
PREFIX ex:       <http://example.org/glossary/>
PREFIX snomed:   <http://snomed.info/id/>
PREFIX rdfs:     <http://www.w3.org/2000/01/rdf-schema#>
PREFIX symp:     <http://purl.obolibrary.org/obo/>
"""

# ── Visualiser ────────────────────────────────────────────────────────────────

visualizer_spec = importlib.util.spec_from_file_location(
    "visualize_glossary", ONTOLOGY_DIR / "visualize_glossary.py"
)
if visualizer_spec is None or visualizer_spec.loader is None:
    raise ImportError("Could not load the graph visualizer.")
visualizer = importlib.util.module_from_spec(visualizer_spec)
sys.modules[visualizer_spec.name] = visualizer
visualizer_spec.loader.exec_module(visualizer)

# ── App ───────────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["SECRET_KEY"] = "local-development-only"
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# ── Shared cache ──────────────────────────────────────────────────────────────
# One parse per file change, shared across every route.

_cache: dict = {"path": None, "mtime": None, "graph": None, "graph_data": None}


def _refresh_cache(ttl_path: Path) -> None:
    mtime = ttl_path.stat().st_mtime
    if _cache["path"] == ttl_path and _cache["mtime"] == mtime:
        return
    g = Graph()
    g.parse(ttl_path, format="turtle")
    _cache["graph"]      = g
    _cache["graph_data"] = visualizer.ttl_to_graph_data(ttl_path)
    _cache["path"]       = ttl_path
    _cache["mtime"]      = mtime


def get_graph(ttl_path: Path) -> Graph:
    _refresh_cache(ttl_path)
    return _cache["graph"]


def get_graph_data(ttl_path: Path) -> dict:
    _refresh_cache(ttl_path)
    return _cache["graph_data"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def active_glossary() -> Path:
    return TEST_GLOSSARY if TEST_GLOSSARY.exists() else DEFAULT_GLOSSARY


def render_index(**context) -> str:
    defaults = {
        "active_task":         "translate",
        "query":               "",
        "from_lang":           "",
        "to_lang":             "",
        "include_clinical":    False,
        "translation_results": [],
        "similar_results":     [],
        "concept_results":     [],
        "symptom_query":       "",
        "target_lang":         "en",
        "symptom_results":     [],
    }
    defaults.update(context)
    ttl = active_glossary()
    defaults["dataset_name"]    = ttl.name
    defaults["is_test_dataset"] = ttl == TEST_GLOSSARY
    return render_template("index.html", **defaults)


def normalize_sparql_query(raw_query: str) -> str:
    """Trim surrounding notes, markdown fences, and stray separator lines from pasted SPARQL."""
    text = (raw_query or "").strip()
    if not text:
        return ""

    # Remove common markdown wrapper blocks.
    text = text.replace("```sparql", "").replace("```", "").strip()

    match = re.search(r"(?is)\b(SELECT|CONSTRUCT|ASK|DESCRIBE)\b", text)
    if match:
        text = text[match.start():].strip()

    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-") and not re.match(r"(?is)^(select|construct|ask|describe)\b", stripped):
            continue
        if stripped.startswith("#") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        lines.append(line)

    return "\n".join(lines).strip()


# ── Routes ────────────────────────────────────────────────────────────────────

ASTHMA_IRI = "http://snomed.info/id/195967001"


@app.route("/graph")
def graph():
    ttl        = active_glossary()
    graph_data = dict(get_graph_data(ttl))   # shallow copy — don't mutate cache
    concept_param = request.args.get("concept", "").strip()
    if concept_param:
        from queries import SNOMED
        graph_data["defaultConcept"] = (
            str(SNOMED[concept_param]) if concept_param.isdigit() else concept_param
        )
    else:
        # Default to Asthma for demo; remove this line to show full graph by default
        graph_data["defaultConcept"] = ASTHMA_IRI
    page = GRAPH_TEMPLATE.read_text(encoding="utf-8").replace(
        "__GRAPH_DATA__", json.dumps(graph_data, ensure_ascii=False)
    )
    return Response(page, mimetype="text/html")


@app.route("/", methods=["GET", "POST"])
def index():
    task = request.form.get("task") or request.args.get("task", "translate")
    if task not in ("translate", "similar", "concept", "symptoms"):
        task = "translate"

    query          = request.form.get("query", "").strip()
    from_lang      = request.form.get("from_lang", "")
    to_lang        = request.form.get("to_lang", "")
    include_clinical = request.form.get("include_clinical") == "1"
    symptom_query  = request.form.get("symptoms", "").strip()
    target_lang    = request.form.get("target_lang", "en")

    translation_results: list[dict] = []
    similar_results:     list[dict] = []
    concept_results:     list[dict] = []
    symptom_results:     list[dict] = []

    if request.method == "POST":
        ttl = active_glossary()
        g   = get_graph(ttl)

        if task == "symptoms" and symptom_query:
            terms = [t.strip() for t in symptom_query.split(",") if t.strip()]
            symptom_results = queries.symptoms_to_diseases(g, terms, target_lang)

        elif query:
            recs = queries.records(g)
            if task == "translate":
                translation_results = queries.translate(
                    recs, query, from_lang, to_lang, include_clinical
                )
            elif task == "similar":
                similar_results = queries.similar(recs, query)
            elif task == "concept":
                concept_results = queries.concept(recs, query)

    return render_index(
        active_task=task,
        query=query,
        from_lang=from_lang,
        to_lang=to_lang,
        include_clinical=include_clinical,
        translation_results=translation_results,
        similar_results=similar_results,
        concept_results=concept_results,
        symptom_query=symptom_query,
        target_lang=target_lang,
        symptom_results=symptom_results,
    )


@app.route("/developer", methods=["GET", "POST"])
def developer():
    if request.method == "POST":
        action = request.form.get("action")

        if action == "reset":
            if TEST_GLOSSARY.exists():
                TEST_GLOSSARY.unlink()
                _cache["path"] = None   # invalidate cache
                flash("The bundled glossary is active again.", "success")
            return redirect(url_for("developer"))

        uploaded = request.files.get("turtle_file")
        if not uploaded or not uploaded.filename:
            flash("Select a Turtle (.ttl) file to upload.", "error")
        elif not uploaded.filename.lower().endswith(".ttl"):
            flash("Only Turtle files with the .ttl extension are accepted.", "error")
        else:
            tmp = TEST_GLOSSARY.with_suffix(".uploading")
            uploaded.save(tmp)
            try:
                g = Graph()
                g.parse(tmp, format="turtle")
                if not g:
                    raise ValueError("The Turtle file contains no triples.")
                tmp.replace(TEST_GLOSSARY)
                _cache["path"] = None   # invalidate cache so next request re-parses
                flash(f"Test dataset activated: {len(g):,} triples loaded.", "success")
            except Exception as error:
                tmp.unlink(missing_ok=True)
                flash(f"The file could not be parsed as Turtle: {error}", "error")

        return redirect(url_for("developer"))

    ttl = active_glossary()
    g = get_graph(ttl)
    shared = queries.shared_symptoms(g, min_diseases=2)
    return render_template(
        "developer.html",
        dataset_name=ttl.name,
        is_test_dataset=ttl == TEST_GLOSSARY,
        sparql_query="",
        sparql_columns=[],
        sparql_rows=[],
        shared_symptoms=shared,
    )


@app.route("/developer/insights")
def developer_insights():
    g      = get_graph(active_glossary())
    ttl    = active_glossary()
    shared = queries.shared_symptoms(g, min_diseases=2)
    return render_template(
        "developer.html",
        dataset_name=ttl.name,
        is_test_dataset=ttl == TEST_GLOSSARY,
        sparql_query="",
        sparql_columns=[],
        sparql_rows=[],
        shared_symptoms=shared,
    )


@app.route("/developer/sparql", methods=["POST"])
def developer_sparql():
    query_text = request.form.get("sparql_query", "").strip()
    columns: list[str] = []
    rows:    list[list[str]] = []

    if query_text:
        try:
            cleaned_query = normalize_sparql_query(query_text)
            if not cleaned_query:
                raise ValueError("No valid SPARQL query was found in the pasted text.")
            full_query = (
                cleaned_query if "PREFIX" in cleaned_query.upper()
                else SPARQL_PREFIXES + cleaned_query
            )
            g      = get_graph(active_glossary())
            result = g.query(full_query)
            columns = [str(v) for v in (result.vars or [])]
            rows    = [
                [("" if val is None else str(val)) for val in row]
                for row in result
            ]
            flash(f"Query returned {len(rows):,} row(s).", "success")
        except Exception as error:
            flash(f"SPARQL query failed: {error}", "error")

    ttl = active_glossary()
    g = get_graph(ttl)
    shared = queries.shared_symptoms(g, min_diseases=2)
    return render_template(
        "developer.html",
        dataset_name=ttl.name,
        is_test_dataset=ttl == TEST_GLOSSARY,
        sparql_query=query_text,
        sparql_columns=columns,
        sparql_rows=rows,
        shared_symptoms=shared,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5001)