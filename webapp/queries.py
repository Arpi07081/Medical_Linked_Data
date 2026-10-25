"""
queries.py — Query functions over the OntoLex-Lemon medical glossary.

Every function takes a loaded rdflib.Graph and returns a list of dicts.
Import this from app.py — no Flask dependency, no file I/O.
"""
from __future__ import annotations

from rdflib import Graph, Literal, RDF, URIRef

# ── Namespaces (hardcoded to avoid import path issues) ────────────────────────

from rdflib.namespace import RDFS, SKOS
from rdflib import Namespace

ONTOLEX  = Namespace("http://www.w3.org/ns/lemon/ontolex#")
VARTRANS = Namespace("http://www.w3.org/ns/lemon/vartrans#")
LIME     = Namespace("http://www.w3.org/ns/lemon/lime#")
SNOMED   = Namespace("http://snomed.info/id/")
SYMP     = Namespace("http://purl.obolibrary.org/obo/")
STY      = Namespace("http://purl.bioontology.org/ontology/STY/")
EX       = Namespace("http://example.org/glossary/")

PFX = """
PREFIX ontolex:  <http://www.w3.org/ns/lemon/ontolex#>
PREFIX vartrans: <http://www.w3.org/ns/lemon/vartrans#>
PREFIX lime:     <http://www.w3.org/ns/lemon/lime#>
PREFIX skos:     <http://www.w3.org/2004/02/skos/core#>
PREFIX ex:       <http://example.org/glossary/>
PREFIX snomed:   <http://snomed.info/id/>
PREFIX rdfs:     <http://www.w3.org/2000/01/rdf-schema#>
PREFIX symp:     <http://purl.obolibrary.org/obo/>
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _concept_type(g: Graph, concept: URIRef) -> str:
    for t in g.objects(concept, RDF.type):
        if t in (EX.Disease, EX.Symptom):
            return str(t).rsplit("/", maxsplit=1)[-1]
    return ""


def _written_reps(g: Graph, entry: URIRef, predicate) -> list[Literal]:
    reps = []
    for form in g.objects(entry, predicate):
        for rep in g.objects(form, ONTOLEX.writtenRep):
            if isinstance(rep, Literal):
                reps.append(rep)
    return reps


# ── 1. All lexical records ────────────────────────────────────────────────────

def records(g: Graph) -> list[dict]:
    """
    All lexical entries (canonical + otherForm) with language, role,
    linked concept, and concept type.
    Used as the base for translate(), similar(), concept().
    """
    result = []

    def collect(form_predicate):
        for entry, _, form in g.triples((None, form_predicate, None)):
            sense   = next(g.objects(entry, ONTOLEX.sense), None)
            concept = next(g.objects(sense, ONTOLEX.reference), None) if sense else None
            rep     = next(g.objects(form, ONTOLEX.writtenRep), None)
            role    = next(g.objects(entry, EX.termRole), None)
            if not (isinstance(rep, Literal) and rep.language and concept):
                continue
            result.append({
                "term":         str(rep),
                "language":     rep.language,
                "concept":      str(concept),
                "concept_id":   str(concept).rsplit("/", maxsplit=1)[-1],
                "is_snomed":    str(concept).startswith(str(SNOMED)),
                "role":         str(role).rsplit("/", maxsplit=1)[-1] if role else "",
                "concept_type": _concept_type(g, concept),
                "entry":        str(entry),
            })

    collect(ONTOLEX.canonicalForm)
    collect(ONTOLEX.otherForm)
    return result


# ── 2. Translate ──────────────────────────────────────────────────────────────

def translate(
    recs: list[dict],
    term: str,
    from_lang: str = "",
    to_lang: str = "",
    include_clinical: bool = False,
) -> list[dict]:
    """
    Given a term, return all other forms sharing the same SNOMED concept.
    Optionally filter by source/target language and include clinical terms.
    """
    term_cf = term.casefold()
    matches = [
        r for r in recs
        if r["term"].casefold() == term_cf
        and (not from_lang or r["language"] == from_lang)
    ]
    if not matches:
        return []
    concepts = {r["concept"] for r in matches}
    return [
        r for r in recs
        if r["concept"] in concepts
        and r["term"].casefold() != term_cf
        and (not to_lang or r["language"] == to_lang)
        and (include_clinical or r["role"] != "ClinicalTerm")
    ]


# ── 3. Similar terms ──────────────────────────────────────────────────────────

def similar(recs: list[dict], keyword: str) -> list[dict]:
    """Return up to 20 entries whose written form contains the keyword."""
    kw = keyword.casefold()
    return [r for r in recs if kw in r["term"].casefold()][:20]


# ── 4. Concept lookup ─────────────────────────────────────────────────────────

def concept(recs: list[dict], snomed_id: str) -> list[dict]:
    """Return all lexical entries linked to the given SNOMED CT numeric ID."""
    return [r for r in recs if r["concept_id"] == snomed_id]


# ── 5. Symptoms → diseases ────────────────────────────────────────────────────

def symptoms_to_diseases(
    g: Graph,
    symptom_terms: list[str],
    target_lang: str = "en",
) -> list[dict]:
    """
    Given one or more symptom terms, return diseases linked via ex:mayIndicate.

    Each input term is resolved to one or more symptom IRIs (a term like
    "Fatigue" may match several symptom nodes). match_count tracks how many
    INPUT TERMS a disease covers, not how many symptom nodes — so 2/2 means
    the disease has symptoms for both of the two terms you entered.

    Diseases covering ALL input terms are returned first; falls back to
    partial matches ranked by term coverage.
    """
    n = len(symptom_terms)

    # Step 1: per input term → set of symptom IRIs it resolves to
    term_symptoms: dict[int, set] = {i: set() for i in range(n)}

    for i, term in enumerate(symptom_terms):
        term_cf = term.casefold()

        for form, _, rep in g.triples((None, ONTOLEX.writtenRep, None)):
            if not (isinstance(rep, Literal) and str(rep).casefold() == term_cf):
                continue
            for entry in g.subjects(ONTOLEX.canonicalForm, form):
                sense   = next(g.objects(entry, ONTOLEX.sense), None)
                symptom = next(g.objects(sense, ONTOLEX.reference), None) if sense else None
                if symptom:
                    term_symptoms[i].add(symptom)
            for entry in g.subjects(ONTOLEX.otherForm, form):
                sense   = next(g.objects(entry, ONTOLEX.sense), None)
                symptom = next(g.objects(sense, ONTOLEX.reference), None) if sense else None
                if symptom:
                    term_symptoms[i].add(symptom)

        # also match rdfs:label on symptom nodes directly
        for symptom, _, label in g.triples((None, RDFS.label, None)):
            if isinstance(label, Literal) and str(label).casefold() == term_cf:
                if (symptom, RDF.type, EX.Symptom) in g:
                    term_symptoms[i].add(symptom)

    # Step 2: for each disease, count how many INPUT TERMS it covers
    disease_term_coverage: dict = {}
    for i, syms in term_symptoms.items():
        for symptom in syms:
            for disease in g.objects(symptom, EX.mayIndicate):
                if disease not in disease_term_coverage:
                    disease_term_coverage[disease] = set()
                disease_term_coverage[disease].add(i)

    if not disease_term_coverage:
        return []

    match_counts = {d: len(terms) for d, terms in disease_term_coverage.items()}

    # Step 3: exact = covers all input terms; otherwise partial fallback
    exact      = {d for d, c in match_counts.items() if c == n}
    candidates = exact if exact else set(match_counts)

    # Step 4: collect lay terms in target_lang
    results: list[dict] = []
    seen: set = set()
    for disease in sorted(candidates, key=lambda d: -match_counts[d]):
        for sense in g.subjects(ONTOLEX.reference, disease):
            for entry in g.subjects(ONTOLEX.sense, sense):
                if next(g.objects(entry, EX.termRole), None) != EX.CommonTerm:
                    continue
                for form in g.objects(entry, ONTOLEX.canonicalForm):
                    for rep in g.objects(form, ONTOLEX.writtenRep):
                        if isinstance(rep, Literal) and rep.language == target_lang:
                            key = (str(disease), str(rep))
                            if key not in seen:
                                seen.add(key)
                                label = next(g.objects(disease, RDFS.label), None)
                                results.append({
                                    "term":          str(rep),
                                    "concept_id":    str(disease).rsplit("/", maxsplit=1)[-1],
                                    "concept_label": str(label) if label else "",
                                    "match_count":   match_counts[disease],
                                    "symptom_count": n,
                                    "is_exact":      disease in exact,
                                })
    return results


# ── 6. Shared symptoms ────────────────────────────────────────────────────────

def shared_symptoms(g: Graph, min_diseases: int = 2) -> list[dict]:
    """
    Return symptoms shared by at least min_diseases diseases.
    Useful for demonstrating the graph hub structure.
    """
    q = PFX + """
    SELECT ?symptomLabel
           (COUNT(DISTINCT ?disease) AS ?diseaseCount)
           (GROUP_CONCAT(DISTINCT ?diseaseLabel; separator=" · ") AS ?diseases)
    WHERE {
        ?symptom a ex:Symptom ; rdfs:label ?symptomLabel .
        ?disease a ex:Disease ; rdfs:label ?diseaseLabel ;
                 ex:hasSymptom ?symptom .
        FILTER(lang(?symptomLabel) = "en" || lang(?symptomLabel) = "")
        FILTER(lang(?diseaseLabel) = "en" || lang(?diseaseLabel) = "")
    }
    GROUP BY ?symptomLabel
    HAVING(COUNT(DISTINCT ?disease) >= %d)
    ORDER BY DESC(?diseaseCount) ?symptomLabel
    """ % min_diseases

    return [
        {
            "symptom":       str(r.symptomLabel),
            "disease_count": int(r.diseaseCount),
            "diseases":      str(r.diseases),
        }
        for r in g.query(q)
    ]