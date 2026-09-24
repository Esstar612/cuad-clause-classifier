# Labeling Schema

Decisions on how CUAD's lawyer-highlighted spans become clause classification labels. Updated as ambiguous cases come up.

## Task format
- **Multi-label.** Each segment gets a set of labels, each with a confidence. An empty set means "none".
- Evidence (Step 1a): 22.8% of spans (3,151 of 13,823) overlap a span of a different category.

## Label set
CUAD has 41 categories. Model labels: 33 plus the implicit "none".

**Extraction categories, treated as no clause type (4).** A segment whose only CUAD categories are these becomes none. It stays in the data because it is real contract text with no clause type.
- Document Name, Parties, Agreement Date, Effective Date
- Reason: they are names and dates (median span 16 to 25 characters), not clause types.

**Kept even though CUAD calls them answer-type categories (4):** Governing Law, Expiration Date, Renewal Term, Notice Period To Terminate Renewal.
- Reason: their spans are clause length (median 178 to 298 characters), so they mark the governing law and term/renewal clauses.

**Merged (2 into 1):** Affiliate License-Licensor (23 contracts) and Affiliate License-Licensee (59 contracts) become **Affiliate License**.

**Dropped as too rare (3):** Source Code Escrow (13 contracts), Price Restrictions (15), Unlimited/All-You-Can-Eat-License (17).
- A segment whose only CUAD categories are these (possibly plus extraction categories) is removed, not relabeled none, so real clauses do not teach "none".
- If such a segment also carries a kept label, it keeps that label and the dropped one is discarded.
- Caveat: the rarity cutoff used label counts across all 510 contracts, including future test contracts. It uses no model output.

**Flagged:** Warranty Duration. Kept, but GitHub issue #23 reports its labels do not match its spec. Report its metrics with that caveat.

## Unit of classification
- A paragraph-like segment produced by `segment_text()`, which works on any raw text (CUAD, PDF text layer, OCR).
- Thresholds frozen 2026-09-23 from train-only statistics (`data/processed/segment_stats.txt`): `min_chars=50`, `max_chars=1500`, `min_coverage=0.5`, stored in `src/config.py`.
- `max_chars` is not a hard cap. A piece shorter than `min_chars` (such as a heading) is folded into the next segment and can push it past `max_chars`. At the frozen settings, 178 of 34,921 train segments exceed 1,500 characters (post-fix split, `data/processed/segment_stats.txt`).

## Span-to-segment labeling
- Spans of the same category within a contract are merged into their union first. Step 1a found 349 overlapping same-category span pairs.
- A segment takes a category when the merged span covers at least `min_coverage` of the span, or at least `min_coverage` of the segment.

## Ambiguous cases

### Case template
- **Case:**
- **Example (contract id, span):**
- **Options considered:**
- **Decision:**
- **Rationale:**
- **Date:**

### Cap On Liability and Uncapped Liability on the same text
- **Case:** 141 overlapping span pairs (Step 1a), although the names sound mutually exclusive.
- **Examples (train contracts, from `data/processed/segment_stats.txt`):**
  - Contract 0, chars 20160-20490: "EXCEPT IN THE EVENT OF A BREACH OF SECTION 11, NEITHER PARTY SHALL BE LIABLE FOR SPECIAL, INCIDENTAL OR CONSEQUENTIAL DAMAGES..." This excludes a type of damages (a limitation) with a carve-out for one breach (uncapped).
  - Contract 3, chars 61460-62882: "11.3. Liability Cap. ... except for any liability (i) relating to any breach associated with the unauthorized use of Intellectual Property, (ii) arising from the intentional breach or willful misconduct..." This is a monetary cap with listed carve-outs.
  - Contract 6, chars 16851-17399: "4.3 LIMITATION OF LIABILITY. EXCEPT FOR PIVX'S OBLIGATIONS UNDER SECTION 4.2, IN NO EVENT SHALL PIVX'S ... LIABILITY ... EXCEED THE TOTAL AMOUNT ACTUALLY RECEIVED BY PIVX HEREUNDER DURING THE PREVIOUS SIX (6) MONTHS..." This is a monetary cap with an indemnity carve-out.
- **Scale:** 95 train segments carry both labels at the frozen settings (post-fix split; 96 before the fix).
- **Options considered:** keep both labels; keep only one; drop such segments.
- **Decision:** keep both, as multi-label. The examples confirm the pattern: the limitation is Cap On Liability, and its carve-outs are Uncapped Liability, so both are true of the same text.
- **Rationale:** it matches the lawyers' annotation. A model that predicts only one of the two on such a segment is partly wrong, not confused.
- **Date:** 2026-09-23

### Extraction-only segments
- **Case:** a segment matched only by Document Name, Parties, Agreement Date, or Effective Date.
- **Decision:** label none.
- **Rationale:** it is real contract text with no clause type; removing it would make the none class unrealistically clean.
- **Date:** 2026-09-23

## Cases from the baseline error analysis (validation only, Step 4a)
Documentation only: no labels were changed. Source: `python -m src.evaluate model baseline | tee data/processed/eval_baseline.txt`. Segment ids are `contract_id_segment_index`; all are validation contracts.

### Volume Restriction: which quantity caps count
- **Case:** CUAD labels some quantity caps as Volume Restriction but not others of the same form.
- **Examples:**
  - Labeled: 180_275, "Wireless Products Up to: 1 Java Game".
  - Labeled: 431_199, "The maximum amount of information downloaded ... will be 15 kilobytes or less per package processed".
  - Not labeled: 17_25, "KI will make one (1) personal appearance per License Year". The baseline gave it p = 0.959 and was counted wrong.
- **Options considered:** treat 17_25 as annotation noise; treat Volume Restriction as limited to product or service quantities; leave as is.
- **Decision:** leave the labels as they are. Record the inconsistency; it partly explains the label's low scores (validation F1 0.286, test F1 0.148).
- **Rationale:** relabeling would break comparability with CUAD and would be made after seeing model errors.
- **Date:** 2026-09-24

### Competitive Restriction Exception: labels without a visible restriction
- **Case:** some segments labeled Competitive Restriction Exception contain no visible restriction or exception. Others that do have that structure are not labeled.
- **Examples:**
  - 326_11 and 326_14 carry the identical text "INTERNATIONAL TEST SYSTEMS RESERVES THE RIGHT TO CHANGE THE RETAIL PRICE AT ANY TIME, WITH NOTICE TO COMWARE." Both are labeled Competitive Restriction Exception, and the text is a pricing right.
  - 180_19, "Neither party may solicit ... provided that the foregoing will not limit Licensee's rights to market and promote ...", has the form of an exception to a restriction but is labeled only Exclusivity.
- **Options considered:** treat the category as defined by context outside the segment; treat as annotation noise.
- **Decision:** document only. The category is defined relative to other clauses, which a single segment may not show.
- **Rationale:** consistent with the baseline's near-zero signal on this label (test AP 0.269) and with the plan to give LLMs the definition, not surrounding context, in Step 3.
- **Date:** 2026-09-24

### Most Favored Nation beyond price
- **Case:** CUAD's Most Favored Nation covers more than pricing.
- **Examples:**
  - 131_54 (allocation in short supply: "Distributor shall be treated no less favorably than any other distributor and shall receive its pro rata allocation").
  - 169_105 (headed "7.2 Most Favored Nation" but about standstill provisions). The baseline gave it p = 0.009 despite the literal heading.
- **Decision:** document only. Prompts in Step 3 should state that the category covers any "no less favorable than others" term, not only price.
- **Date:** 2026-09-24

### Labels on heavily redacted text
- **Case:** a segment whose operative words are redacted still carries a clause label.
- **Example:** 51_272, labeled Competitive Restriction Exception: "In the event [***], [***] in a manner that (x) [***], (y) [***] or (z) [***] ...".
- **Decision:** keep the label; note that no model can recover it from the visible text. Redaction markers appear in 110 contracts (Step 1a).
- **Date:** 2026-09-24
