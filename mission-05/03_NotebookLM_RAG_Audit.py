"""
Mission 05 — Part 3: Data & Payload Specialist
Google NotebookLM Grounding & Citation Audit — scoring script

Starship Operational Unit: USSE Noosphere Bridge Crew
Sector: SEC-05-M01 (Crab Pulsar Remnant / Messier 1)
Subsystem 05: Dual-Path Associative Memory Core
Officer: Abubaker Attique / Squadron Goodfellow Group 18

What this script does
---------------------
The audit itself was done by hand in NotebookLM: every citation badge in each
response was clicked, and the highlighted passage in the source viewer was read
against the assertion it supports. Each badge became one row in a CSV file with
a verdict:

    supported    the passage states the assertion or directly entails it
    partial      the passage is on topic and consistent, but does not state the
                 specific detail (a number, a named mechanism, an absence claim)
    unsupported  the passage does not bear on the assertion

This script reads those CSV files and computes, with no hand-typed numbers:

    Citation Precision = True Entailed Citations / Total Citations Generated

reported two ways:

    strict   only "supported" badges count as entailed (headline figure)
    lenient  "supported" plus "partial" badges count

It also summarises the claim-level files, the three epistemic-refusal probes and
the Audio Overview scores. Standard library only.

Usage
-----
    python3 03_NotebookLM_RAG_Audit.py                 # text report
    python3 03_NotebookLM_RAG_Audit.py --markdown      # GitHub tables
    python3 03_NotebookLM_RAG_Audit.py --json out.json # machine-readable summary
    python3 03_NotebookLM_RAG_Audit.py --check         # exit 1 if the CSV totals
                                                       # differ from the lab file

Input files (same folder as this script)
----------------------------------------
    citation_audit_q1.csv .. citation_audit_q5.csv   one row per badge
    citation_audit_q2_claims.csv .. _q5_claims.csv   one row per assertion
    citation_audit_p2.csv                            badges inside probe P2
    refusal_probes.csv                               one row per probe

Limits: verdicts were assigned by Claude (an AI assistant) and are subject to
the author's spot-check; a badge audit tests whether the cited passage supports
the sentence, not whether the sentence is true.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent

QUERIES = ["q1", "q2", "q3", "q4", "q5"]
SUPPORTED, PARTIAL, UNSUPPORTED = "supported", "partial", "unsupported"
BADGE_VERDICTS = (SUPPORTED, PARTIAL, UNSUPPORTED)
CLAIM_VERDICTS = (SUPPORTED, PARTIAL, UNSUPPORTED, "uncited")

# Totals reported in Section 2.7 of the lab file, used only by --check so that
# the written report and the CSV files cannot drift apart unnoticed.
LAB_FILE_TOTALS = {
    "q1": (84, 54, 29, 1),
    "q2": (157, 58, 98, 1),
    "q3": (12, 8, 4, 0),
    "q4": (0, 0, 0, 0),
    "q5": (9, 3, 6, 0),
    "all": (262, 123, 137, 2),
}

# Audio Overview scores, copied from Section 3 of the lab file (scored from the
# transcript text; the author's listening notes are pending). Update both
# places together.
AUDIO_OVERVIEW = {
    "recording": "How GraphRAG Summarized Massive Datasets (4:26, Deep Dive)",
    "scores": {
        "Factual Fidelity": 4,
        "Persona Differentiation": 4,
        "Pedagogical Value": 4,
    },
    "claim_check": {
        "supported": 8,
        "supported with one word added": 1,
        "overstated": 2,
        "misleading": 1,
        "not in the sources": 1,
        "speculation": 1,
    },
}


# --------------------------------------------------------------------------
# Reading the CSV files
# --------------------------------------------------------------------------
def read_csv(name: str) -> List[Dict[str, str]]:
    path = HERE / name
    if not path.exists():
        raise FileNotFoundError(f"missing input file: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


# --------------------------------------------------------------------------
# Citation Precision
# --------------------------------------------------------------------------
def citation_precision(rows: List[Dict[str, str]]) -> Dict[str, object]:
    """Strict and lenient Citation Precision for a list of badge rows."""
    counts = Counter(row["verdict"].strip().lower() for row in rows)
    unknown = set(counts) - set(BADGE_VERDICTS)
    if unknown:
        raise ValueError(f"unknown verdict(s) in badge file: {sorted(unknown)}")
    total = sum(counts.values())
    supported, partial = counts[SUPPORTED], counts[PARTIAL]
    return {
        "badges": total,
        SUPPORTED: supported,
        PARTIAL: partial,
        UNSUPPORTED: counts[UNSUPPORTED],
        # Precision is undefined with no badges (0 of 0), not zero.
        "strict": supported / total if total else None,
        "lenient": (supported + partial) / total if total else None,
    }


def by_source(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, object]]:
    sources = sorted({row["source"] for row in rows})
    return {
        src: citation_precision([r for r in rows if r["source"] == src])
        for src in sources
    }


def claim_level(rows: List[Dict[str, str]]) -> Dict[str, object]:
    """Claim-level view: do the cited passages together entail the assertion?"""
    counts = Counter(row["claim_level_verdict"].strip().lower() for row in rows)
    unknown = set(counts) - set(CLAIM_VERDICTS)
    if unknown:
        raise ValueError(f"unknown verdict(s) in claims file: {sorted(unknown)}")
    cited = sum(counts[v] for v in BADGE_VERDICTS)
    single = sum(
        1
        for row in rows
        if row.get("fully_supported_by_a_single_badge", "").strip().lower()
        in {"s", "yes", "true", "1", "y"}  # "S" = one badge supports the whole assertion
    )
    return {
        "assertions": len(rows),
        "cited": cited,
        "uncited": counts["uncited"],
        SUPPORTED: counts[SUPPORTED],
        PARTIAL: counts[PARTIAL],
        UNSUPPORTED: counts[UNSUPPORTED],
        "single_badge_support": single,
        "claim_level_supported": counts[SUPPORTED] / cited if cited else None,
    }


# --------------------------------------------------------------------------
# Whole audit
# --------------------------------------------------------------------------
def run_audit() -> Dict[str, object]:
    per_query: Dict[str, Dict[str, object]] = {}
    all_rows: List[Dict[str, str]] = []
    claims: Dict[str, Dict[str, object]] = {}

    for q in QUERIES:
        rows = read_csv(f"citation_audit_{q}.csv")
        all_rows.extend(rows)
        per_query[q] = citation_precision(rows)
        per_query[q]["by_source"] = by_source(rows)
        claims_file = HERE / f"citation_audit_{q}_claims.csv"
        if claims_file.exists():
            claims[q] = claim_level(read_csv(claims_file.name))

    overall = citation_precision(all_rows)
    overall["by_source"] = by_source(all_rows)

    probes = read_csv("refusal_probes.csv")
    p2_rows = read_csv("citation_audit_p2.csv")

    scores = AUDIO_OVERVIEW["scores"]
    return {
        "queries": per_query,
        "overall": overall,
        "claim_level": claims,
        "probes": {
            "count": len(probes),
            "outcomes": dict(Counter(p["outcome"] for p in probes)),
            "rows": probes,
            "p2_badges": citation_precision(p2_rows),
        },
        "audio": {**AUDIO_OVERVIEW, "mean_score": sum(scores.values()) / len(scores)},
    }


def check_against_lab_file(result: Dict[str, object]) -> List[str]:
    """Compare CSV-derived totals with the numbers written in the lab file."""
    problems = []
    rows = dict(result["queries"])
    rows["all"] = result["overall"]
    for key, expected in LAB_FILE_TOTALS.items():
        got = (
            rows[key]["badges"],
            rows[key][SUPPORTED],
            rows[key][PARTIAL],
            rows[key][UNSUPPORTED],
        )
        if got != expected:
            problems.append(f"{key}: CSV gives {got}, lab file says {expected}")
    return problems


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def print_text(result: Dict[str, object]) -> None:
    print("=" * 78)
    print("NotebookLM grounding audit: Citation Precision")
    print("=" * 78)
    header = f"{'Query':<10}{'Badges':>7}{'Supp.':>7}{'Part.':>7}{'Unsup.':>7}{'Strict':>10}{'Lenient':>10}"
    print(header)
    print("-" * len(header))
    for q in QUERIES:
        r = result["queries"][q]
        print(
            f"{q.upper():<10}{r['badges']:>7}{r[SUPPORTED]:>7}{r[PARTIAL]:>7}"
            f"{r[UNSUPPORTED]:>7}{pct(r['strict']):>10}{pct(r['lenient']):>10}"
        )
    o = result["overall"]
    print("-" * len(header))
    print(
        f"{'ALL':<10}{o['badges']:>7}{o[SUPPORTED]:>7}{o[PARTIAL]:>7}"
        f"{o[UNSUPPORTED]:>7}{pct(o['strict']):>10}{pct(o['lenient']):>10}"
    )
    print("\nBy source document (all five queries):")
    for src, r in o["by_source"].items():
        print(
            f"  {src:<14} {r['badges']:>4} badges   strict {pct(r['strict']):>6}"
            f"   lenient {pct(r['lenient']):>6}"
        )

    print("\nClaim level (do the cited passages together entail the assertion?):")
    for q, c in result["claim_level"].items():
        print(
            f"  {q.upper()}: {c['assertions']} assertions, {c['cited']} cited, "
            f"{c['uncited']} uncited; of the cited, {c[SUPPORTED]} supported, "
            f"{c[PARTIAL]} partial ({pct(c['claim_level_supported'])}); "
            f"{c['single_badge_support']} supported by a single badge"
        )

    p = result["probes"]
    print("\nEpistemic-refusal probes:")
    for row in p["rows"]:
        print(f"  {row['probe_id']} ({row['probe_type']}): {row['outcome']}; badges: {row['badges']}")
    b = p["p2_badges"]
    print(
        f"  P2 badge audit: {b['badges']} badges, {b[SUPPORTED]} supported, "
        f"{b[PARTIAL]} partial; strict {pct(b['strict'])}, lenient {pct(b['lenient'])}"
    )

    a = result["audio"]
    print(f"\nAudio Overview: {a['recording']}")
    for metric, score in a["scores"].items():
        print(f"  {metric:<26} {score}/5")
    print(f"  {'Mean':<26} {a['mean_score']:.1f}/5")
    print("  Claim check: " + ", ".join(f"{v} {k}" for k, v in a["claim_check"].items()))


def print_markdown(result: Dict[str, object]) -> None:
    print("| Query | Badges | Supported | Partial | Unsupported | Strict precision | Lenient precision |")
    print("| :--- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for q in QUERIES:
        r = result["queries"][q]
        if r["badges"] == 0:
            print(f"| {q.upper()} | 0 | – | – | – | n/a | n/a |")
        else:
            print(
                f"| {q.upper()} | {r['badges']} | {r[SUPPORTED]} | {r[PARTIAL]} | "
                f"{r[UNSUPPORTED]} | {pct(r['strict'])} | {pct(r['lenient'])} |"
            )
    o = result["overall"]
    print(
        f"| **All five** | {o['badges']} | {o[SUPPORTED]} | {o[PARTIAL]} | "
        f"{o[UNSUPPORTED]} | {pct(o['strict'])} | {pct(o['lenient'])} |"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--markdown", action="store_true", help="print the results table as Markdown")
    parser.add_argument("--json", metavar="PATH", help="write the full summary as JSON")
    parser.add_argument("--check", action="store_true", help="compare CSV totals with the lab file")
    args = parser.parse_args()

    result = run_audit()

    if args.markdown:
        print_markdown(result)
    else:
        print_text(result)

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")

    if args.check:
        problems = check_against_lab_file(result)
        if problems:
            print("\nCHECK FAILED:")
            for line in problems:
                print("  " + line)
            return 1
        print("\nCHECK PASSED: CSV totals match Section 2.7 of the lab file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
