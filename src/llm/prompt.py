"""Prompt versions for the LLM classifiers (Step 3).

Category definitions are loaded verbatim from CUAD: the "Details:" text of each question in
CUAD_v1.json, which matches the official category_descriptions.csv for all 41 categories.
Categories are listed in CUAD's own order, so the Competitive Restriction Exception
definition ("...Non-Compete, Exclusivity and No-Solicit of Customers above") still points
upward correctly. Rules come only from docs/labeling_schema.md.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from src import config
from src.data import load_raw_json
from src.labels import MERGED, model_label

V1_INSTRUCTIONS = """You label clauses in commercial contracts for a contract review system.

You will receive a window of consecutive text segments from one contract. Each segment has an id and a role. Label only the segments with role="target". Segments with role="context" are there so you can read the targets in context: do not give a target a category that appears only in a neighboring segment.

For each target segment, list every category below that you judge at least somewhat likely to apply to that segment itself (confidence 0.1 or higher), each with your confidence from 0 to 1 that it applies. A segment can have several categories. Most segments in a contract have none of these categories; for those, return an empty list.

Rules:
- The names of the contract or of the parties, and dates, are not categories here. A segment that only states them gets an empty list unless it also contains one of the categories.
- A limitation of liability with exceptions can be both "Cap On Liability" (the limitation) and "Uncapped Liability" (the exceptions).
- "Most Favored Nation" covers any term entitling a party to terms no less favorable than those given to others, not only price.

Return JSON only: one entry per target segment, with the id exactly as given and category names exactly as listed below.

Categories (definitions from the Contract Understanding Atticus Dataset, written by the lawyers who labeled it):"""

PROMPT_VERSIONS = {
    "v1": {"instructions": V1_INSTRUCTIONS,
           "notes": "zero-shot; CUAD definitions verbatim; the 3 labeling-schema rules"},
}

REFRAME = (
    "Each category comes with its definition from the Contract Understanding Atticus Dataset. "
    "The definitions are written as questions about the whole contract; read each one as "
    "describing a type of clause. A target segment gets a category when the segment itself "
    'contains a clause of that type: for example, a clause choosing the law that governs the '
    'agreement is "Governing Law", and a clause stating when the initial term ends is '
    '"Expiration Date". Confidence is your probability that the segment contains such a clause. '
    "Do not list a category you have ruled out.")

EVIDENCE = ("For each category you list, first give evidence: a short quote, at most 15 words, "
            "from the target segment that shows the clause. Then give your confidence.")


def _with_reframe(instructions: str, extra: str = "") -> str:
    para = REFRAME + (" " + extra if extra else "")
    return instructions.replace("\n\nRules:\n", f"\n\n{para}\n\nRules:\n", 1)


# Kept out of PROMPT_VERSIONS so probe variants can never be adopted or frozen.
PROBE_VARIANTS = {
    "probe_A": {"instructions": V1_INSTRUCTIONS, "effort": "medium",
                "notes": "v1 text, effort medium"},
    "probe_B": {"instructions": _with_reframe(V1_INSTRUCTIONS), "effort": "low",
                "notes": "v1 + reframing, effort low"},
    "probe_C": {"instructions": _with_reframe(V1_INSTRUCTIONS, EVIDENCE), "effort": "low",
                "evidence": True, "notes": "B + evidence quote, effort low"},
    "probe_D": {"instructions": _with_reframe(V1_INSTRUCTIONS), "effort": "medium",
                "notes": "B at effort medium"},
    "probe_E": {"instructions": V1_INSTRUCTIONS, "effort": "low",
                "notes": "control: v1 rerun, fresh namespace"},
}


V2_INSTRUCTIONS = """You label clauses in commercial contracts for a contract review system.

You will receive a window of consecutive text segments from one contract. Each segment has an id and a role. Label only the segments with role="target". Segments with role="context" are there so you can read the targets in context: do not give a target a category that appears only in a neighboring segment.

For each target segment, list every category below that you judge at least somewhat likely to apply to that segment itself (confidence 0.1 or higher), each with your confidence from 0 to 1 that it applies. A segment can have several categories. Most segments in a contract have none of these categories; for those, return an empty list.

""" + REFRAME + """ Never list a category with confidence below 0.1.

Rules:
- The names of the contract or of the parties, and the dates of signing or effectiveness, are not categories here. A segment that only states them gets an empty list unless it also contains one of the categories. Dates and periods that a category below describes, such as when the term ends or renews, the notice period to prevent renewal, or how long a warranty lasts, are labeled with that category.
- A limitation of liability with exceptions can be both "Cap On Liability" (the limitation) and "Uncapped Liability" (the exceptions).
- "Most Favored Nation" covers any term entitling a party to terms no less favorable than those given to others, not only price.
- An assignment clause that mentions mergers, sales of all or substantially all assets, or assignment by operation of law only as ways an assignment can happen is usually "Anti-Assignment" only. Also label it "Change Of Control" when the clause treats a change in a party's ownership or control as an event with its own consequences: for example, it deems a change of control to be an assignment, or gives a right to terminate because of one.

Return JSON only: "segments" has one key per target id, exactly as given, holding that segment's list of categories (an empty list if none), with category names exactly as listed below.

Categories (definitions from the Contract Understanding Atticus Dataset, written by the lawyers who labeled it):"""

PROMPT_VERSIONS["v2"] = {"instructions": V2_INSTRUCTIONS, "schema": "keyed",
                         "notes": "keyed schema; reframing; floor sentence; narrowed rule 1; Change Of Control note"}


EXAMPLES_PARAGRAPH = (
    "Before the window you will see examples: segments from other contracts, with the categories "
    "CUAD's lawyers gave them, chosen because they resemble the targets. Use them to see how the "
    "categories are applied. They are not part of this contract; do not label them.")

_CONTEXT_END = "do not give a target a category that appears only in a neighboring segment.\n\n"
V3_INSTRUCTIONS = V2_INSTRUCTIONS.replace(_CONTEXT_END, _CONTEXT_END + EXAMPLES_PARAGRAPH + "\n\n", 1)

PROMPT_VERSIONS["v3"] = {"instructions": V3_INSTRUCTIONS, "schema": "keyed", "retrieval": True,
                         "notes": "v2 + per target the nearest labeled and nearest overall train segment"}


def _edit(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"expected exactly one occurrence of {old[:50]!r}")
    return text.replace(old, new)


V4_EDITS = (
    ("For each target segment, list every category below that you judge at least somewhat likely to apply "
     "to that segment itself (confidence 0.1 or higher), each with your confidence from 0 to 1 that it "
     "applies. A segment can have several categories. Most segments in a contract have none of these "
     "categories; for those, return an empty list.",
     "For each target segment, give every category below your confidence from 0 to 1 that it applies to "
     "that segment itself. A segment can have several categories. Most segments in a contract have none "
     "of these categories; for those, every confidence should be low."),
    (" Do not list a category you have ruled out. Never list a category with confidence below 0.1.", ""),
    ("gets an empty list unless it also contains one of the categories",
     "gets a low confidence for every category unless it also contains one of the categories"),
    ('Return JSON only: "segments" has one key per target id, exactly as given, holding that segment\'s '
     "list of categories (an empty list if none), with category names exactly as listed below.",
     'Return JSON only: "segments" has one key per target id, exactly as given, each holding a confidence '
     "for every category, with category names exactly as listed below."),
)
V4_INSTRUCTIONS = V3_INSTRUCTIONS
for _old, _new in V4_EDITS:
    V4_INSTRUCTIONS = _edit(V4_INSTRUCTIONS, _old, _new)

PROMPT_VERSIONS["v4"] = {"instructions": V4_INSTRUCTIONS, "schema": "keyed", "retrieval": True,
                         "output": "dense", "notes": "v3 with a confidence for every label (dense output)"}


def version_spec(version: str) -> dict:
    return PROMPT_VERSIONS[version] if version in PROMPT_VERSIONS else PROBE_VARIANTS[version]


@lru_cache(maxsize=1)
def _cuad_questions() -> tuple[tuple[str, str], ...]:
    """(category, definition) in CUAD order, definitions verbatim (no stripping)."""
    qas = load_raw_json()["data"][0]["paragraphs"][0]["qas"]
    return tuple((qa["id"].rsplit("__", 1)[1], qa["question"].split("Details: ", 1)[1]) for qa in qas)


def label_definition(label: str) -> str:
    defs = dict(_cuad_questions())
    merged = [cat for cat, target in MERGED.items() if target == label]  # Licensor, then Licensee
    if merged:
        return "Either of the following. (a) " + defs[merged[0]] + " (b) " + defs[merged[1]]
    return defs[label]


def ordered_labels(label_order: list[str]) -> list[str]:
    """The kept labels in CUAD's category order (a merged label at its first member)."""
    out = []
    for cat, _ in _cuad_questions():
        lab = model_label(cat)
        if lab and lab not in out:
            out.append(lab)
    assert sorted(out) == sorted(label_order), "prompt labels differ from the model's label set"
    return out


@lru_cache(maxsize=None)
def _system_prompt(version: str, labels: tuple[str, ...]) -> str:
    lines = [version_spec(version)["instructions"], ""]
    lines += [f'- "{lab}": {label_definition(lab)}' for lab in ordered_labels(list(labels))]
    return "\n".join(lines)


def system_prompt(version: str, label_order: list[str]) -> str:
    """Fixed per version: the cached prefix."""
    return _system_prompt(version, tuple(label_order))


def output_schema(label_order: list[str], evidence: bool = False, target_ids: list[str] | None = None,
                  dense: bool = False) -> dict:
    """Confidence bounds are checked in parse.py: Claude's structured outputs lack numeric min/max."""
    if dense:
        if target_ids is None:
            raise ValueError("dense output needs target ids")
        confidences = {"type": "object", "properties": {lab: {"type": "number"} for lab in sorted(label_order)},
                       "required": sorted(label_order), "additionalProperties": False}
        segments = {"type": "object", "properties": {t: confidences for t in target_ids},
                    "required": list(target_ids), "additionalProperties": False}
        return {"type": "object", "properties": {"segments": segments},
                "required": ["segments"], "additionalProperties": False}
    props = {"label": {"type": "string", "enum": sorted(label_order)}}
    if evidence:
        props["evidence"] = {"type": "string"}
    props["confidence"] = {"type": "number"}
    label_item = {"type": "object", "properties": props,
                  "required": list(props), "additionalProperties": False}
    labels = {"type": "array", "items": label_item}
    if target_ids is None:
        segment = {"type": "object", "properties": {"id": {"type": "string"}, "labels": labels},
                   "required": ["id", "labels"], "additionalProperties": False}
        segments = {"type": "array", "items": segment}
    else:
        segments = {"type": "object", "properties": {t: labels for t in target_ids},
                    "required": list(target_ids), "additionalProperties": False}
    return {"type": "object", "properties": {"segments": segments},
            "required": ["segments"], "additionalProperties": False}


def user_message(call, examples: list[dict] | None = None) -> tuple[str, dict[str, str]]:
    """The window as XML-like segments with local ids S1..Sn in document order.
    Returns (message, local id -> segment id)."""
    local = {f"S{i + 1}": sid for i, sid in enumerate(call.segment_ids)}
    targets = set(call.targets)
    parts = [f'<segment id="{lid}" role="{"target" if sid in targets else "context"}">\n'
             f"{call.texts[i]}\n</segment>"
             for i, (lid, sid) in enumerate(local.items())]
    window = "<window>\n" + "\n".join(parts) + "\n</window>"
    if examples is None:
        return window, local
    shown = "\n".join(f'<example labels="{"; ".join(e["labels"]) or "none"}">\n{e["text"]}\n</example>'
                      for e in examples)
    return f"<examples>\n{shown}\n</examples>\n{window}", local


def schema_for(version: str, label_order: list[str], target_ids: list[str] | None = None) -> dict:
    spec = version_spec(version)
    ids = None
    if spec.get("schema") == "keyed":
        ids = target_ids or [f"S{i + 1}" for i in range(config.LLM_WINDOW_SIZE)]  # full-window template for the prompt hash
    return output_schema(label_order, evidence=spec.get("evidence", False), target_ids=ids,
                         dense=spec.get("output") == "dense")


def prompt_hash(version: str, label_order: list[str]) -> str:
    blob = system_prompt(version, label_order) + json.dumps(schema_for(version, label_order), sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
