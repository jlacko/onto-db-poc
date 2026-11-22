"""Shared paths, namespaces and helpers."""
from pathlib import Path

from rdflib import Graph, Namespace

ROOT = Path(__file__).resolve().parent.parent
ONTO = ROOT / "ontology"
REF = ONTO / "reference"
TESTS = ONTO / "tests"
BUILD = ROOT / "build"
CACHE = BUILD / "cache"
DB_DIR = ROOT / "db"

API = "https://kriminalita.policie.gov.cz/api/v2/downloads"

KRIM = Namespace("https://example.org/kriminalita/ontology#")
KRIMC = Namespace("https://example.org/kriminalita/code/")
KDB = Namespace("https://example.org/kriminalita/db#")
VS = Namespace("http://www.w3.org/2003/06/sw-vocab-status/ns#")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")

# codelist name in the API -> (krim class local name, concept-scheme slug)
SCHEMES = {
    "types": ("OffenceType", "type"),
    "states": ("ClearanceState", "state"),
    "relevance": ("LocationRelevance", "relevance"),
}


def bind(g: Graph) -> Graph:
    g.bind("krim", KRIM)
    g.bind("krimc", KRIMC)
    g.bind("kdb", KDB)
    g.bind("vs", VS)
    g.bind("geo", GEO)
    return g


def load_graph(*paths) -> Graph:
    g = bind(Graph())
    for p in paths:
        g.parse(p)
    return g


def model_files():
    """Ontology plus reference data (no shapes, no samples)."""
    return [ONTO / "kriminalita.ttl", *sorted(REF.glob("*.ttl"))]
