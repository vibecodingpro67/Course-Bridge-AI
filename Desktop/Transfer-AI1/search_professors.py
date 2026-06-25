import gzip, json, os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_json_or_gz(base_path):
    for path in (base_path + ".gz", base_path):
        if not os.path.exists(path):
            continue
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return []


_professors_path = os.path.join(BASE_DIR, "data", "professors.json")
_professors_cache = None


def _get_professors():
    global _professors_cache
    if _professors_cache is None:
        _professors_cache = _load_json_or_gz(_professors_path)
        # flatten nested format if needed
        if isinstance(_professors_cache, dict):
            edges = _professors_cache.get("data", {}).get("newSearch", {}).get("teachers", {}).get("edges", [])
            _professors_cache = [e["node"] for e in edges if isinstance(e, dict) and "node" in e]
    return _professors_cache

SUBJECT_KEYWORDS = [
    "english", "biology", "computer", "history", "math", "mathematics",
    "physics", "chemistry", "psychology", "business", "accounting",
    "economics", "sociology", "art", "music", "philosophy", "nursing",
    "engineering", "statistics", "political", "anthropology", "geography",
    "kinesiology", "communications", "journalism", "architecture",
]


def search_professors(query):
    _professors = _get_professors()
    q = query.lower()

    # Detect subject
    subject = None
    for kw in SUBJECT_KEYWORDS:
        if kw in q:
            subject = kw
            break

    # Detect school name (simple word match)
    school_hint = None
    for prof in _professors[:500]:  # sample to find unique school names
        school = prof.get("school", "")
        if not school:
            continue
        school_words = [w for w in school.lower().split()
                        if len(w) >= 4 and w not in {"college", "community", "district"}]
        if any(w in q for w in school_words):
            school_hint = school.lower()
            break

    matches = []
    for prof in _professors:
        searchable = (
            prof.get("firstName", "").lower() + " " +
            prof.get("lastName", "").lower() + " " +
            prof.get("department", "").lower() + " " +
            prof.get("school", "").lower()
        )

        # Filter by school if detected
        if school_hint:
            if school_hint not in prof.get("school", "").lower():
                continue

        # Filter by subject if detected
        if subject:
            if subject not in searchable:
                continue

        # Require at least 3 ratings
        if prof.get("numRatings", 0) < 3:
            continue

        matches.append(prof)

    # Bayesian weighted score: pulls low-count ratings toward the global mean.
    # score = (v * R + m * C) / (v + m)
    #   v = numRatings, R = avgRating, C = global mean (3.86), m = weight threshold (20)
    C = 3.86
    m = 20

    def _score(p):
        v = p.get("numRatings", 0)
        R = p.get("avgRating", 0)
        return (v * R + m * C) / (v + m)

    matches.sort(key=_score, reverse=True)
    return matches[:5]
