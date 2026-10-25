# Medical Linked Data

Local RDF/Turtle glossary data and a Flask web interface for terminology tasks.

## Project Layout

| Path | Purpose |
| --- | --- |
| `ontology/ttl/glossary.ttl` | Active bundled bilingual glossary in RDF/Turtle. |
| `ontology/csv/medical_terms.csv` | Disease source table (common vs. clinical/FSN term pairs, SNOMED IDs). |
| `ontology/csv/medical_symptoms.csv` | Optional disease-symptom links, used to add `hasSymptom`/`mayIndicate` triples. |
| `ontology/generate_glossary.py` | Converts the CSV sources into `ontology/ttl/glossary.ttl`. |
| `ontology/visualize_glossary.py` | Converts `glossary.ttl` into the data consumed by the `/graph` view. |
| `ontology/graph_template.html` | Source HTML/JS template for the graph visualization (has the `__GRAPH_DATA__` placeholder). |
| `ontology/sparql_query_generator.py` | Interactive Fuseki-backed term translator, plus a library of rdflib SPARQL query use-cases (`run_all`). |
| `ontology/queries_to_run.md` | Sample SPARQL queries. |
| `ontology/terminologie-snomed-ct-Janvier 2026 v1.0.owl` | Original SNOMED CT ontology source. |
| `webapp/` | Flask application and browser templates. |
| `webapp/app.py` | Application entry point. |
| `webapp/templates/` | HTML templates for public and developer pages, including the baked `graph.html`. |
| `webapp/requirements.txt` | Python dependencies for the web application. |
| `webapp/active-test-glossary.ttl` | Optional test dataset created via `/developer`. |

## Prerequisites

- Python 3.11 or later
- `pip`

```bash
python3 --version
```

## Installation

Run these commands from the `MedicalLinkedData` directory:

```bash
cd webapp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Activate the virtual environment again whenever you open a new terminal:

```bash
cd webapp
source .venv/bin/activate
```

## Run the Application

From the `MedicalLinkedData` directory:

```bash
cd webapp
source .venv/bin/activate
python app.py
```

Open [http://127.0.0.1:5001](http://127.0.0.1:5001). Stop the server with `Control-C`.

The Flask debug reloader does not automatically pick up changes to `ontology/visualize_glossary.py` on all setups — if you edit it, restart `python app.py`.

## Public Tasks

- **Translate a term:** retrieves the English or Spanish lexical form connected to the same SNOMED concept.
- **Find similar terms:** performs a case-insensitive text match across the local glossary. This is not semantic similarity.
- **Look up a SNOMED concept:** retrieves glossary forms associated with a SNOMED CT identifier.

All public tasks query `ontology/ttl/glossary.ttl`, unless a developer test dataset is active.

## Graph Visualization

Open [http://127.0.0.1:5001/graph](http://127.0.0.1:5001/graph) for an interactive D3 view of the active glossary: Disease/Symptom concept nodes, Common/Clinical lexical entries, and `registerVariant`/`translation`/`hasSymptom`/`mayIndicate` edges. Filter by concept, register, or type, and search across terms and SNOMED FSNs.

## Developer Test Dataset

Open [http://127.0.0.1:5001/developer](http://127.0.0.1:5001/developer) to upload a Turtle test dataset.

1. Select a `.ttl` file.
2. Select **Validate and activate**.
3. Test the public tasks against the uploaded graph.
4. Select **Restore default dataset** to return to `glossary.ttl`.

The application validates the RDF syntax before activation. It stores a valid upload at `webapp/active-test-glossary.ttl` and does not overwrite the bundled glossary. The maximum upload size is 10 MB.

## Regenerate the Glossary

After editing `ontology/csv/medical_terms.csv` (and optionally `ontology/csv/medical_symptoms.csv`), run:

```bash
source webapp/.venv/bin/activate
cd ontology
python generate_glossary.py
python visualize_glossary.py
```

`generate_glossary.py` writes `ontology/ttl/glossary.ttl`; `visualize_glossary.py` rebuilds `webapp/templates/graph.html` for the `/graph` view.

`medical_terms.csv` requires `English Common Term`, `English Main Term`, `Spanish Common Term`, `Spanish Main Term`, and `SNOMED Concept ID` headers (an optional `STY_ID` column adds a UMLS semantic-type alignment). `medical_symptoms.csv` requires `Disease SNOMED` plus at least one of `English Symptom`/`Spanish Symptom` (optional `Symptom SNOMED`, `SYMP_ID`, `STY_ID`, `Source` columns are used when present). A `Symptom SNOMED` value that matches any known disease/concept ID is ignored (falls back to a local ID) to avoid the symptom's URI colliding with that concept.

## SPARQL Query Examples

`ontology/sparql_query_generator.py` doubles as:

- An interactive translator against a running Apache Jena Fuseki instance (`python sparql_query_generator.py`, requires the `SPARQLWrapper` package and a Fuseki server serving the `glossary` dataset at `http://localhost:3030/glossary/sparql`).
- A library of ready-made rdflib queries over a local `glossary.ttl` file — translate common/clinical terms, concept details, symptoms-to-diseases, similar terms, shared symptoms, and all-language lookups (`python sparql_query_generator.py ontology/ttl/glossary.ttl` runs a demo of all of them via `run_all`).

## Troubleshooting

| Problem | Resolution |
| --- | --- |
| `ModuleNotFoundError: No module named 'flask'` | Run `cd webapp`, activate `.venv`, then run `python -m pip install -r requirements.txt`. |
| Browser cannot connect | Confirm `python app.py` is running from `webapp`, then reopen `http://127.0.0.1:5001`. |
| Address already in use | Stop the process using port 5001, or change `port=5001` in `webapp/app.py`. |
| No search results | Confirm the term or SNOMED identifier exists in the active glossary dataset. |
| `/graph` page renders blank | Restart `python app.py` so it picks up the latest `ontology/visualize_glossary.py`, or re-run `python ontology/visualize_glossary.py` to rebake `webapp/templates/graph.html`. |
| `ModuleNotFoundError: No module named 'SPARQLWrapper'` | Only needed for the interactive Fuseki translator in `sparql_query_generator.py`; run `python -m pip install SPARQLWrapper` if you use that mode. |
