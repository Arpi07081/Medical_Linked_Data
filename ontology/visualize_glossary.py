from rdflib import Graph, Literal, RDF, RDFS
import json, re, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
from namespaces import ONTOLEX, VARTRANS, EX, SKOS


# ── Label helpers ─────────────────────────────────────────────────────────────

_FSN_RE = re.compile(r"^(.*?)\s*\([^()]+\)\s*$")


def short(uri: str) -> str:
    s = str(uri)
    return s.split("#")[-1].split("/")[-1]


def strip_fsn(label: str) -> str:
    """Remove SNOMED FSN semantic tag: 'Asthma (disorder)' → 'Asthma'."""
    m = _FSN_RE.match(label)
    return m.group(1).strip() if m else label


def truncate_symptom(label: str, max_len: int = 40) -> str:
    """
    Shorten long MedlinePlus symptom descriptions to something readable
    as a graph node label. Splits on ' - ', comma, or parenthesis.
    """
    label = label.strip()
    if len(label) <= max_len:
        return label
    for sep in (" - ", ", ", " (", "; "):
        part = label.split(sep)[0].strip()
        if 4 <= len(part) <= max_len:
            return part
    return label[:max_len].rstrip(" ,-(") + "…"


def best_label(g: Graph, uri, prefer_lang: str = "en") -> str:
    """
    Pick the best rdfs:label for a URI.
    Prefers the requested language; falls back to untagged, then any language.
    """
    preferred = untagged = fallback = None
    for label in g.objects(uri, RDFS.label):
        if not isinstance(label, Literal):
            continue
        if label.language == prefer_lang:
            preferred = str(label)
        elif label.language is None and untagged is None:
            untagged = str(label)
        elif fallback is None:
            fallback = str(label)
    return preferred or untagged or fallback or short(str(uri))


# ── Main extraction ───────────────────────────────────────────────────────────

def ttl_to_graph_data(ttl_path):
    g = Graph()
    g.parse(ttl_path)

    nodes: dict = {}
    edges: list = []

    def add(uri, ntype, label, **extra):
        key = str(uri)
        if key not in nodes:
            node = {"id": key, "type": ntype, "label": label}
            node.update(extra)
            nodes[key] = node

    # Disease / Symptom concept nodes
    for concept_class, ntype in ((EX.Disease, "disease"), (EX.Symptom, "symptom")):
        for concept in g.subjects(RDF.type, concept_class):
            raw = best_label(g, concept)
            clean = strip_fsn(raw)
            if ntype == "symptom":
                clean = truncate_symptom(clean)
            symp = [str(o) for o in g.objects(concept, SKOS.exactMatch)]
            sty  = [str(o) for o in g.objects(concept, SKOS.closeMatch)]
            sctid = short(str(concept))
            add(concept, ntype, f"{clean}\n({sctid})", symp=symp, sty=sty,
                concept_label=clean)

    # LexicalEntry — language from writtenRep, register from ex:termRole
    for entry in g.subjects(RDF.type, ONTOLEX.LexicalEntry):
        lang, label = "?", short(str(entry))
        for form in g.objects(entry, ONTOLEX.canonicalForm):
            for rep in g.objects(form, ONTOLEX.writtenRep):
                if isinstance(rep, Literal):
                    label = str(rep)
                    lang  = rep.language or "?"
        role = short(str(next(iter(g.objects(entry, EX.termRole)), "unknown")))
        other_forms = [
            str(rep)
            for other_form in g.objects(entry, ONTOLEX.otherForm)
            for rep in g.objects(other_form, ONTOLEX.writtenRep)
        ]
        add(entry, f"entry_{lang}_{role}", f"{label}\n({lang.upper()})",
            lang=lang, role=role, otherForms=other_forms, alts=[])

    # LexicalSense
    for sense in g.subjects(RDF.type, ONTOLEX.LexicalSense):
        alts = [str(a) for a in g.objects(sense, SKOS.altLabel)]
        add(sense, "sense", "sense", alts=alts)

    # Edges — only what the visualisation renders
    WANTED = {
        str(ONTOLEX.sense):        "sense",
        str(ONTOLEX.reference):    "reference",
        str(VARTRANS.translation): "translation",
        str(EX.registerVariant):   "registerVariant",
        str(EX.hasSymptom):        "hasSymptom",
        str(EX.mayIndicate):       "mayIndicate",
    }
    for s, p, o in g:
        label = WANTED.get(str(p))
        if label:
            s_str, o_str = str(s), str(o)
            if s_str in nodes and o_str in nodes:
                edges.append({"from": s_str, "to": o_str, "label": label})

    # Metadata for dropdowns
    roles = sorted({n["role"] for n in nodes.values() if "role" in n})
    types = sorted({n["type"] for n in nodes.values()
                    if n["type"] in ("disease", "symptom")})

    # Concept dropdown: concept IRI → EN common-term label
    # Prefer the entry's written form over the rdfs:label (cleaner for common terms)
    concepts: dict = {}
    for sense, _, concept in g.triples((None, ONTOLEX.reference, None)):
        for entry in g.subjects(ONTOLEX.sense, sense):
            en = nodes.get(str(entry), {})
            if en.get("lang") == "en" and en.get("role") == "CommonTerm":
                concepts[str(concept)] = en["label"].split("\n")[0]

    # Fall back to rdfs:label for concepts not reached via a CommonTerm entry
    for concept in list(g.subjects(RDF.type, EX.Disease)) + \
                   list(g.subjects(RDF.type, EX.Symptom)):
        key = str(concept)
        if key not in concepts:
            n = nodes.get(key)
            if n:
                concepts[key] = n["concept_label"]

    return {
        "nodes":    list(nodes.values()),
        "edges":    edges,
        "concepts": concepts,
        "roles":    roles,
        "types":    types,
    }


def build(ttl_path, output_path="webapp/templates/graph.html",
          template_path="graph_template.html"):
    data = ttl_to_graph_data(ttl_path)
    template_path = Path(template_path)
    if not template_path.is_absolute():
        template_path = SCRIPT_DIR / template_path
    output_path = Path(output_path)
    if not output_path.is_absolute():
        output_path = SCRIPT_DIR.parent / output_path
    with template_path.open(encoding="utf-8") as f:
        html = f.read()
    html = html.replace("__GRAPH_DATA__", json.dumps(data))
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Written {output_path} — {len(data['nodes'])} nodes, {len(data['edges'])} edges")


def main():
    ttl_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SCRIPT_DIR / "ttl" / "glossary.ttl"
    if not ttl_path.exists():
        sys.exit(f"TTL file not found: {ttl_path}")
    build(ttl_path)


if __name__ == "__main__":
    main()