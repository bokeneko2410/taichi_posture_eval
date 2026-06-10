# Taichi Posture Evaluation Tool
### Markerless pose estimation for self-practice feedback (work in progress)

> **Full documentation is in Japanese.** Use an AI translator on `README.md` and `spec/taichi_eval_spec_v1.2.md` for details.

---

## What it does

Take a photo of a Taichi key pose during self-practice. The tool evaluates your posture against training principles (*yōjué* — the instructional checkpoints of each movement) and returns feedback in plain language.

No markers or special equipment. Works with a smartphone + Mac.

```
Photo (smartphone) → Pose extraction (MediaPipe) → Per-principle evaluation → Feedback
"Right elbow is flaring outward (78° from vertical)"
"Weight slightly back (actual 6:4 / target 7:3 front-to-rear)"
```

---

## Motivation

Standard markerless motion analysis tools (e.g. SPLYZA Motion) output joint angles — but joint angles alone don't map to Taichi training principles. Key problems:

- "Sink the shoulders" (*chén jiān*) can't be judged by comparing your angle to someone else's; what matters is **how much you dropped from your own raised baseline**.
- What's actually useful in long-term practice is not today's snapshot but **the trend of improvement over months**.

These constraints forced a custom measurement model.

---

## Technical highlights

### Four-type measurement model

Each evaluation principle is classified by what it compares *against*:

| Type | Reference | Example |
|------|-----------|---------|
| A — Structural | Absolute geometry | Knee must not pass the toe |
| B — Reference form | Official form spec + master's range | Rear-leg angle in bow stance |
| C — Retained baseline | Change from your own neutral posture | Shoulder-sinking rate |
| D — Habit release | Release from your own habitual tension | Pelvic tilt, chest containment |

Types C and D are **self-referential** — they start from your own body's habits, not population norms. This is the core design insight.

### Elbow direction (墜肘) from 2D landmarks

MediaPipe's 33 landmarks include no "elbow orientation." The tool reconstructs the olecranon direction geometrically as the **reverse of the angle bisector** of shoulder–elbow–wrist, then measures outward deviation from vertical. When the arm is nearly straight, the measurement is flagged as geometrically undefined rather than emitting a bad value.

### Raw-value-first data storage

Thresholds (e.g. "elbow deviation ≤ 45° = OK") are kept separate as tunable parameters. The JSONL log stores only **raw measurements**. This means:
- Changing a threshold never invalidates past data
- Re-extracting after a model update regenerates full history from photos

### Analysis engine design (planned)

Comparisons are modelled as a two-axis query:

```
Evaluation = target selector (--target) × reference selector (--vs)
```

New comparison types add one comparator; no new programs needed.

---

## Current status

| Phase | Status |
|-------|--------|
| Prototype (skeleton viz, diff overlay) | Done |
| Phase 1: Data capture program | Implemented, self-tested |
| Phase 1.5: Type-D experiments (pelvis, scapula) | Not started |
| Phase 2: Analysis engine + trend reports | Designed, not implemented |
| Phase 3: Auto key-pose extraction from video | Under consideration |

---

## Repository layout

```
spec/            Specifications (Markdown, v1.0–v1.2)
flow/            Processing flow diagrams (draw.io XML)
code_prototype/  Initial prototype
code_phase1/     Phase 1: data capture
note/            Design notes
```

---

## Stack

- Python 3.12 / MediaPipe Pose Landmarker
- OpenCV / NumPy / Matplotlib
- JSONL (flat format, queryable with awk/jq)
- draw.io

---

## About the author

30 years in industrial/chemical safety, followed by IT management, communications, and workflow automation. Side projects in kintone / Google Apps Script / Python internal tooling. Started this project from personal practice needs. Ongoing as a post-retirement personal project.
