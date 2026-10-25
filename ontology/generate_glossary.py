"""Generate an OntoLex-Lemon glossary (with Disease/Symptom typing) from medical CSV files.

Reads medical_terms.csv (diseases, common vs. clinical/FSN term pairs) and, if present,
medical_symptoms.csv (disease -> symptom links) to build a bilingual glossary graph.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

from rdflib import Graph, Literal, OWL, RDF, RDFS

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))  # repo root, for the shared namespaces module
from namespaces import ONTOLEX, LEXINFO, VARTRANS, LIME, SNOMED, SYMP, STY, DC, EX, SKOS

SYMP_ROOT = "SYMP_0000462"  # root class of the Symptom Ontology (SYMP)
FSN_SUFFIX_RE = re.compile(r"^(.*?)\s*\(([^()]+)\)\s*$")


def clean(value: str | None) -> str:
    return " ".join((value or "").split())


def term_id(term: str) -> str:
    identifier = re.sub(r"[^a-z0-9]+", "_", term.casefold()).strip("_")
    return identifier or "unnamed_term"


def first_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = clean(row.get(name))
        if value:
            return value
    return ""


def split_fsn(main_term: str) -> tuple[str, str | None]:
    """Split a SNOMED FSN like 'Myocardial infarction (disorder)' into (canonical, full_fsn)."""
    match = FSN_SUFFIX_RE.match(main_term)
    if not match:
        return main_term, None
    return match.group(1).strip(), main_term


def concept_type(main_term: str, row: dict[str, str]) -> str:
    explicit_type = first_value(row, "dc:type", "Type", "Concept Type", "Category").casefold()
    if explicit_type in {"disease", "symptom"}:
        return explicit_type
    return "symptom" if "finding" in main_term.casefold() else "disease"


def bind_namespaces(graph: Graph) -> None:
    for prefix, namespace in {
        "ontolex": ONTOLEX, "lexinfo": LEXINFO, "vartrans": VARTRANS, "lime": LIME,
        "snomed": SNOMED, "symp": SYMP, "sty": STY, "dc": DC, "skos": SKOS, "ex": EX,
    }.items():
        graph.bind(prefix, namespace)


def add_schema(graph: Graph) -> None:
    """Assert the fixed class/property hierarchy shared by every generated glossary."""
    graph.add((EX.MedicalConcept, RDF.type, OWL.Class))
    graph.add((EX.MedicalConcept, RDFS.label, Literal("Medical Concept")))

    graph.add((EX.Disease, RDF.type, OWL.Class))
    graph.add((EX.Disease, RDFS.subClassOf, EX.MedicalConcept))
    graph.add((EX.Disease, RDFS.label, Literal("Disease")))

    graph.add((EX.Symptom, RDF.type, OWL.Class))
    graph.add((EX.Symptom, RDFS.subClassOf, EX.MedicalConcept))
    graph.add((EX.Symptom, RDFS.subClassOf, SYMP[SYMP_ROOT]))
    graph.add((EX.Symptom, RDFS.label, Literal("Symptom")))

    graph.add((EX.TermRole, RDF.type, RDFS.Class))
    graph.add((EX.CommonTerm, RDF.type, EX.TermRole))
    graph.add((EX.ClinicalTerm, RDF.type, EX.TermRole))

    graph.add((EX.termRole, RDF.type, RDF.Property))
    graph.add((EX.termRole, RDFS.domain, ONTOLEX.LexicalEntry))
    graph.add((EX.termRole, RDFS.range, EX.TermRole))

    graph.add((EX.registerVariant, RDF.type, OWL.SymmetricProperty))
    graph.add((EX.registerVariant, RDFS.domain, ONTOLEX.LexicalEntry))
    graph.add((EX.registerVariant, RDFS.range, ONTOLEX.LexicalEntry))

    graph.add((EX.hasSymptom, RDF.type, OWL.ObjectProperty))
    graph.add((EX.hasSymptom, RDFS.domain, EX.Disease))
    graph.add((EX.hasSymptom, RDFS.range, EX.Symptom))

    graph.add((EX.mayIndicate, RDF.type, OWL.ObjectProperty))
    graph.add((EX.mayIndicate, RDFS.domain, EX.Symptom))
    graph.add((EX.mayIndicate, RDFS.range, EX.Disease))


def add_term_entries(graph: Graph, lexicon: object, lang: str, common_term: str,
                      main_term: str, concept_uri: object) -> tuple[object | None, object | None]:
    """Create the Common-term entry and, if the FSN differs, a linked Clinical-term entry.

    Returns (common_sense, clinical_sense_or_None) so callers can wire up translations.
    """
    if not common_term:
        return None, None

    # A lay term should never carry a SNOMED FSN suffix (e.g. when the CSV had no
    # dedicated Common Term and fell back to the FSN itself).
    common_term, _ = split_fsn(common_term)

    common_id = term_id(common_term)
    entry = EX[f"entry_{common_id}_{lang}"]
    form = EX[f"form_{common_id}_{lang}"]
    sense = EX[f"sense_{common_id}_{lang}"]

    graph.add((lexicon, LIME.entry, entry))
    graph.add((entry, RDF.type, ONTOLEX.LexicalEntry))
    graph.add((entry, EX.termRole, EX.CommonTerm))
    graph.add((entry, LEXINFO.partOfSpeech, LEXINFO.noun))
    graph.add((entry, ONTOLEX.canonicalForm, form))
    graph.add((form, ONTOLEX.writtenRep, Literal(common_term, lang=lang)))
    graph.add((entry, ONTOLEX.sense, sense))
    graph.add((sense, RDF.type, ONTOLEX.LexicalSense))
    graph.add((sense, ONTOLEX.reference, concept_uri))
    graph.add((sense, ONTOLEX.denotes, concept_uri))

    clinical_term = clean(main_term)
    if not clinical_term:
        return sense, None

    canonical_clinical, fsn_full = split_fsn(clinical_term)
    if canonical_clinical.casefold() == common_term.casefold() and not fsn_full:
        return sense, None

    clinical_id = term_id(canonical_clinical)
    if clinical_id == common_id:
        clinical_id = f"{clinical_id}_clinical"
    clinical_entry = EX[f"entry_{clinical_id}_{lang}"]
    clinical_form = EX[f"form_{clinical_id}_{lang}"]
    clinical_sense = EX[f"sense_{clinical_id}_{lang}"]

    graph.add((lexicon, LIME.entry, clinical_entry))
    graph.add((clinical_entry, RDF.type, ONTOLEX.LexicalEntry))
    graph.add((clinical_entry, EX.termRole, EX.ClinicalTerm))
    graph.add((clinical_entry, LEXINFO.partOfSpeech, LEXINFO.noun))
    graph.add((clinical_entry, ONTOLEX.canonicalForm, clinical_form))
    graph.add((clinical_form, ONTOLEX.writtenRep, Literal(canonical_clinical, lang=lang)))
    if fsn_full and fsn_full.casefold() != canonical_clinical.casefold():
        fsn_form = EX[f"form_{clinical_id}_fsn_{lang}"]
        graph.add((clinical_entry, ONTOLEX.otherForm, fsn_form))
        graph.add((fsn_form, ONTOLEX.writtenRep, Literal(fsn_full, lang=lang)))
    graph.add((clinical_entry, ONTOLEX.sense, clinical_sense))
    graph.add((clinical_sense, RDF.type, ONTOLEX.LexicalSense))
    graph.add((clinical_sense, ONTOLEX.reference, concept_uri))
    graph.add((clinical_sense, ONTOLEX.denotes, concept_uri))

    graph.add((entry, EX.registerVariant, clinical_entry))
    graph.add((clinical_entry, EX.registerVariant, entry))

    return sense, clinical_sense


def add_disease_terms(graph: Graph, lexicon_en: object, lexicon_es: object, input_path: Path) -> set[str]:
    """Returns the set of SNOMED concept IDs used, so add_symptom_links can guard against reused IDs."""
    concept_ids: set[str] = set()
    with input_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            english_common = first_value(row, "English Common Term", "English", "English Main Term")
            english_main = first_value(row, "English Main Term")
            spanish_common = first_value(row, "Spanish Common Term", "Spanish", "Spanish Main Term")
            spanish_main = first_value(row, "Spanish Main Term")
            concept_id = first_value(row, "SNOMED Concept ID", "SNOMED")
            if not english_common or not concept_id:
                continue
            concept_ids.add(concept_id)

            concept_uri = SNOMED[concept_id]
            kind = concept_type(english_main or english_common, row)
            graph.add((concept_uri, RDF.type, EX.Symptom if kind == "symptom" else EX.Disease))
            graph.add((concept_uri, RDFS.label, Literal(english_main or english_common, lang="en")))
            sty_id = first_value(row, "STY_ID", "STY Id", "UMLS STY")
            if sty_id:
                graph.add((concept_uri, SKOS.closeMatch, STY[sty_id]))

            en_common_sense, en_clinical_sense = add_term_entries(
                graph, lexicon_en, "en", english_common, english_main, concept_uri)

            # Spanish common term may be missing; fall back to the Spanish FSN if so.
            spanish_common_or_fallback = spanish_common or spanish_main
            es_common_sense = es_clinical_sense = None
            if spanish_common_or_fallback:
                es_common_sense, es_clinical_sense = add_term_entries(
                    graph, lexicon_es, "es", spanish_common_or_fallback, spanish_main, concept_uri)

            if en_common_sense and es_common_sense:
                graph.add((en_common_sense, VARTRANS.translation, es_common_sense))
            if en_clinical_sense and es_clinical_sense:
                graph.add((en_clinical_sense, VARTRANS.translation, es_clinical_sense))

            source = first_value(row, "Source of symptoms (Medline plus)", "Source")
            if source:
                for sense in (en_common_sense, es_common_sense):
                    if sense:
                        graph.add((sense, DC.source, Literal(source)))

    return concept_ids


def add_symptom_entry(graph: Graph, lexicon: object, lang: str, text: str,
                       symptom_uri: object, source: str) -> object:
    entry_id = f"symptom_{term_id(text)}_{lang}"
    entry = EX[f"entry_{entry_id}"]
    form = EX[f"form_{entry_id}"]
    sense = EX[f"sense_{entry_id}"]

    graph.add((lexicon, LIME.entry, entry))
    graph.add((entry, RDF.type, ONTOLEX.LexicalEntry))
    graph.add((entry, EX.termRole, EX.CommonTerm))
    graph.add((entry, LEXINFO.partOfSpeech, LEXINFO.noun))
    graph.add((entry, ONTOLEX.canonicalForm, form))
    graph.add((form, ONTOLEX.writtenRep, Literal(text, lang=lang)))
    graph.add((entry, ONTOLEX.sense, sense))
    graph.add((sense, RDF.type, ONTOLEX.LexicalSense))
    graph.add((sense, ONTOLEX.reference, symptom_uri))
    graph.add((sense, ONTOLEX.denotes, symptom_uri))
    if source:
        graph.add((sense, DC.source, Literal(source)))
    return sense


def add_symptom_links(graph: Graph, lexicon_en: object, lexicon_es: object, input_path: Path,
                       known_concept_ids: set[str]) -> None:
    """Optionally link diseases to symptoms via medical_symptoms.csv (skipped if absent)."""
    if not input_path.exists():
        return

    with input_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            disease_id = first_value(row, "Disease SNOMED")
            english_text = first_value(row, "English Symptom")
            spanish_text = first_value(row, "Spanish Symptom")
            if not disease_id or (not english_text and not spanish_text):
                continue

            symptom_snomed = first_value(row, "Symptom SNOMED")
            # Skip short, code-less fragments (e.g. rows produced by a comma splitting a
            # longer sentence across CSV cells) rather than treating them as real symptoms.
            if english_text and len(english_text.split()) < 3 and not symptom_snomed:
                continue

            disease_uri = SNOMED[disease_id]
            graph.add((disease_uri, RDF.type, EX.Disease))

            # Guard against bad CSV data reusing a disease's own SNOMED ID as the symptom code
            # (that would make the symptom's URI collide with that disease's own URI).
            if symptom_snomed in known_concept_ids:
                symptom_snomed = ""
            primary_text = english_text or spanish_text
            symptom_uri = SNOMED[symptom_snomed] if symptom_snomed else EX[f"symptom_{term_id(primary_text)}"]
            graph.add((symptom_uri, RDF.type, EX.Symptom))
            if english_text:
                graph.add((symptom_uri, RDFS.label, Literal(english_text, lang="en")))
            if spanish_text:
                graph.add((symptom_uri, RDFS.label, Literal(spanish_text, lang="es")))
            graph.add((disease_uri, EX.hasSymptom, symptom_uri))
            graph.add((symptom_uri, EX.mayIndicate, disease_uri))

            symp_id = first_value(row, "SYMP_ID")
            if symp_id:
                graph.add((symptom_uri, SKOS.exactMatch, SYMP[symp_id]))
            sty_id = first_value(row, "STY_ID")
            if sty_id:
                graph.add((symptom_uri, SKOS.closeMatch, STY[sty_id]))

            source = first_value(row, "Source")
            en_sense = add_symptom_entry(graph, lexicon_en, "en", english_text, symptom_uri, source) if english_text else None
            es_sense = add_symptom_entry(graph, lexicon_es, "es", spanish_text, symptom_uri, source) if spanish_text else None
            if en_sense and es_sense:
                graph.add((en_sense, VARTRANS.translation, es_sense))


def generate(input_path: Path, output_path: Path, symptoms_path: Path) -> tuple[int, int]:
    graph = Graph()
    bind_namespaces(graph)
    add_schema(graph)

    lexicon_en = EX.lexicon_en
    lexicon_es = EX.lexicon_es
    graph.add((lexicon_en, RDF.type, LIME.Lexicon))
    graph.add((lexicon_en, LIME.language, Literal("en")))
    graph.add((lexicon_es, RDF.type, LIME.Lexicon))
    graph.add((lexicon_es, LIME.language, Literal("es")))

    known_concept_ids = add_disease_terms(graph, lexicon_en, lexicon_es, input_path)
    add_symptom_links(graph, lexicon_en, lexicon_es, symptoms_path, known_concept_ids)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(graph.serialize(format="turtle"), encoding="utf-8")
    return len(graph), len(set(graph.subjects(RDF.type, ONTOLEX.LexicalEntry)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=SCRIPT_DIR / "csv/medical_terms.csv")
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "ttl" / "glossary.ttl")
    parser.add_argument("--symptoms", type=Path, default=SCRIPT_DIR / "csv/medical_symptoms.csv",
                         help="Optional disease-symptom CSV; skipped if the file is missing.")
    args = parser.parse_args()
    input_path = args.input if args.input.is_absolute() else Path.cwd() / args.input
    output_path = args.output if args.output.is_absolute() else Path.cwd() / args.output
    symptoms_path = args.symptoms if args.symptoms.is_absolute() else Path.cwd() / args.symptoms
    if not input_path.exists():
        parser.error(f"CSV file not found: {input_path}")
    triples, entries = generate(input_path, output_path, symptoms_path)
    print(f"Generated {entries} lexical entries and {triples} triples: {output_path}")


if __name__ == "__main__":
    main()
