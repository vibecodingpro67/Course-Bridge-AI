import gzip
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_json_or_gz(base_path):
    """Try .gz first, then .json, return [] on failure."""
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


_courses_path = os.path.join(BASE_DIR, "data", "all_transferable_courses.json")
_courses_cache = None


def _get_courses():
    global _courses_cache
    if _courses_cache is None:
        _courses_cache = _load_json_or_gz(_courses_path)
    return _courses_cache


def search_courses(query):
    courses = _get_courses()

    query = query.lower()

    matches = []

    # DETECT SCHOOL
    school_detected = None

    all_schools = set()

    for course in courses:

        if "school" in course:

            all_schools.add(
                course["school"]
            )

    # PRIORITIZE FULL SCHOOL NAME MATCHES
    for school in all_schools:

        school_lower = school.lower()

        # exact full phrase match
        if school_lower in query:

            school_detected = school_lower
            break

    # SECONDARY MATCHING
    if not school_detected:

        for school in all_schools:

            school_lower = school.lower()

            # remove common suffixes
            simplified = (
                school_lower
                .replace("college", "")
                .replace("community", "")
                .strip()
            )

            if simplified in query:

                school_detected = school_lower
                break

    # SUBJECT DETECTION — collect ALL matching subjects, not just the first
    subjects = [
        "math", "biology", "chemistry", "physics", "economics",
        "business", "computer", "english", "history", "psychology",
        "statistics", "calculus", "accounting", "sociology", "political",
        "engineering", "nursing", "kinesiology", "communications",
    ]

    subjects_detected = [s for s in subjects if s in query]

    # STRICT FILTERING
    for course in courses:

        searchable = ""
        for key, value in course.items():
            if isinstance(value, str):
                searchable += value.lower() + " "

        # REQUIRE SCHOOL MATCH when school is detected
        if school_detected:
            if (
                "school" not in course
                or course["school"].lower() != school_detected
            ):
                continue

        # REQUIRE AT LEAST ONE SUBJECT MATCH when subjects are detected
        if subjects_detected:
            if not any(s in searchable for s in subjects_detected):
                continue

        matches.append(course)

    # REMOVE DUPLICATES
    unique_matches = []
    seen = set()

    for match in matches:
        key = (
            match.get("school", ""),
            match.get("prefix", ""),
            match.get("courseNumber", "")
        )
        if key not in seen:
            seen.add(key)
            unique_matches.append(match)

    # Return more results when a specific school is detected (schedule building needs broad data)
    limit = 40 if school_detected else 20
    return unique_matches[:limit]