# My Contribution — Medical Linked Data Knowledge Graph

## Overview

My contribution to the **Medical Linked Data** project focused on the Python implementation for building an **English–Spanish medical terminology knowledge graph** using RDF and OntoLex-Lemon. The implementation transforms structured medical terminology records into connected lexical entries, medical concepts, and disease–symptom relationships.

This document highlights the contribution represented by two files:

- [`generate_glossary.py`](generate_glossary.py) — RDF knowledge graph generation and OntoLex-Lemon modeling.
- [`namespaces.py`](namespaces.py) — centralized declarations of the namespaces and vocabularies used by the graph.

## 1. RDF Knowledge Graph Construction

**File:** `generate_glossary.py`

I implemented the graph-generation logic using **Python** and **RDFLib** to convert source CSV records into an RDF knowledge graph serialized in **Turtle (`.ttl`)** format.

The workflow:

1. Reads terminology from `medical_terms.csv` and optionally disease–symptom relations from `medical_symptoms.csv`.
2. Normalizes terms and extracts canonical clinical labels from SNOMED fully specified names (FSNs).
3. Constructs an ontology schema for `MedicalConcept`, `Disease`, and `Symptom`.
4. Builds English and Spanish lexical entries and maps their senses to standardized medical concepts.
5. Adds translation, common-versus-clinical register, and disease–symptom relationships.
6. Serializes the resulting RDF graph as `glossary.ttl`.

**Relevant functions:** `clean()`, `term_id()`, `split_fsn()`, `add_schema()`, `add_disease_terms()`, `add_symptom_links()`, and `generate()`.

## 2. OntoLex-Lemon Modeling

**File:** `generate_glossary.py` — especially `add_term_entries()`

A central part of the implementation is the use of **OntoLex-Lemon** to distinguish *linguistic expressions* from the *medical concepts* they represent.

- `ontolex:LexicalEntry` represents a medical term.
- `ontolex:canonicalForm` connects an entry to its primary written form.
- `ontolex:writtenRep` stores the text with an English (`en`) or Spanish (`es`) language tag.
- `ontolex:LexicalSense` and `ontolex:reference` connect an entry to its corresponding medical concept.
- `ex:termRole` distinguishes common/patient-facing vocabulary from clinical terminology.
- `ex:registerVariant` links common and clinical entries expressing the same concept.
- `vartrans:translation` links English and Spanish lexical senses.

**Illustrative structure:**

```text
English term → LexicalEntry → LexicalSense → SNOMED CT concept
                                                    ↑
Spanish term → LexicalEntry → LexicalSense ─────────┘
```

This is **concept-based terminology linking**, not machine-learning-based translation.

## 3. Medical Ontology and Disease–Symptom Relationships

**File:** `generate_glossary.py` — especially `add_schema()` and `add_symptom_links()`

The graph defines `Disease` and `Symptom` as subclasses of `MedicalConcept` and connects them with explicit RDF properties:

```text
Disease → ex:hasSymptom → Symptom
Symptom → ex:mayIndicate → Disease
```

Where source identifiers are available, medical concepts are represented with **SNOMED CT** URIs. Optional mappings use **SKOS** to link concepts to the **Symptom Ontology (SYMP)** and UMLS semantic-type resources (`STY`). The implementation also handles incomplete source records and guards against conflicting symptom/disease identifiers.

These relationships support structured traversal and querying rather than relying only on string matching.

## 4. Namespace and Vocabulary Integration

**File:** `namespaces.py`

I organized shared URI namespaces for consistent reuse in the RDF graph-generation code, including:

| Vocabulary | Role in the project |
|---|---|
| OntoLex-Lemon | Lexical entries, forms, senses, and conceptual references |
| LexInfo | Linguistic annotations such as part of speech |
| VarTrans | Translation relationships between lexical senses |
| LIME | Language-specific lexicons |
| SNOMED CT | Standardized clinical concept identifiers |
| SYMP | Symptom ontology alignment |
| STY | UMLS semantic-type references |
| SKOS | Cross-vocabulary concept mappings |
| Dublin Core | Source/provenance metadata |
| `ex:` | Project-specific classes and relationships |

## Output and Scope

The main generated artifact is **`glossary.ttl`**, an RDF/Turtle medical terminology graph containing lexical entries, medical concepts, translations, register variants, and disease–symptom links.

The two Python files document the **graph-building implementation**. The underlying medical CSV input files are required to regenerate the data; they are not included in this code-focused contribution subset. Other parts of the full project, including the Flask interface and D3 visualization, are outside the scope of this contribution document.
