"""CF Game Studio: the provenance record on every draft and candidate (model-quality plan, section 5).

Every draft (DB draft or offline best-of-N candidate) carries one record. Nothing is trained in rungs 0-2; the
record exists so that rows can later be checked by a fail-closed training-set builder, and so eval results are tied
to a prompt/brief version.

Taint rules implemented here (plan section 5):
- rule 1: ANY call (write, repair, review, revise, doctrine) whose served model is not an allow-listed self-hosted
  model, or whose base is not the M4/loopback, taints the row. DeepSeek is allowed only for privacy=public rows.
- rule 7: taint is sticky through `parent_id` and `edit_assisted`.
- privacy defaults to private; public only if every source key is public.
Stdlib only.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import uuid

SCHEMA = "studio-provenance/1"
ALLOWED_HOSTS = frozenset({"100.64.0.3", "127.0.0.1"})
ALLOWED_MODEL_PREFIXES = ("mlx-community/qwen3-coder-30b-a3b", "mlx-community/qwen3-30b-a3b-thinking",
                          "mlx-community/qwen3-vl-4b")
CLOSED_MARKERS = ("claude", "anthropic", "fable", "opus", "sonnet", "haiku", "luna", "gpt", "gemini", "openai")
DEEPSEEK = "deepseek"


def config_hash(**parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def call_problem(call: dict, privacy: str) -> str:
    """'' when the call is clean, else why it taints the row."""
    model = str((call or {}).get("model") or "").lower()
    base = str((call or {}).get("base") or "")
    if not model:
        return f"{call.get('role', '?')}: served model unknown"
    if DEEPSEEK in model:
        return "" if privacy == "public" else f"{call.get('role', '?')}: DeepSeek on a private row"
    if any(m in model for m in CLOSED_MARKERS) or not model.startswith(ALLOWED_MODEL_PREFIXES):
        return f"{call.get('role', '?')}: model {model!r} is not an allow-listed self-hosted model"
    host = urllib.parse.urlsplit(base).hostname if base else None
    if host not in ALLOWED_HOSTS:
        return f"{call.get('role', '?')}: base {base!r} is not the M4/loopback"
    return ""


def record(*, course_id, week, split, calls, prompt_version, brief_hash, sampling, config=None,
           gate_verdicts=None, gate_models=None, source_privacy=None, parent=None, edit_assisted=False,
           human_label="none", human_edited=False, draft_id=None, extra=None) -> dict:
    """Build the section-5 record. `calls` = [{role, model (as served), base}] for EVERY call made.
    `source_privacy` = list of per-source privacy labels ('public'/'private'); missing = private."""
    privacy = "public" if source_privacy and all(p == "public" for p in source_privacy) else "private"
    reasons = [r for r in (call_problem(c, privacy) for c in calls or []) if r]
    if not calls:
        reasons.append("no model calls recorded")
    if parent and parent.get("provenance") != "clean":
        reasons.append(f"parent {parent.get('draft_id')} is tainted")
    if edit_assisted is not False:
        reasons.append("edited with closed-model assistance")
    roles = {c.get("role"): c.get("model") for c in calls or []}
    rec = {
        "schema": SCHEMA, "draft_id": draft_id or ("d" + uuid.uuid4().hex[:11]), "created_at": time.time(),
        "course_id": course_id, "week": week, "split": split,
        "writer_model": roles.get("write"), "writer_endpoint": next((c.get("base") for c in calls or []
                                                                     if c.get("role") == "write"), None),
        "reviewer_model": roles.get("review"), "doctrine_model": (gate_models or {}).get("doctrine"),
        "prompt_version": prompt_version, "brief_hash": brief_hash, "sampling": sampling,
        "config_hash": config_hash(prompt_version=prompt_version, brief_hash=brief_hash, sampling=sampling,
                                   **(config or {})),
        "gate_verdicts": gate_verdicts or {}, "gate_models": gate_models or {},
        "human_label": human_label, "human_edited": bool(human_edited), "edit_assisted": edit_assisted,
        "privacy": privacy, "calls": list(calls or []), "parent_id": (parent or {}).get("draft_id"),
        "provenance": "tainted" if reasons else "clean", "taint_reason": "; ".join(reasons),
    }
    if extra:
        rec.update({k: v for k, v in extra.items() if k not in rec})
    return rec


def verdicts_from_card(card) -> tuple[dict, dict]:
    """(gate_verdicts {gate: pass|fail|infra}, gate_models {gate: model}) from a studio gate card."""
    v, models = {}, {}
    for g in (card or {}).get("gates") or []:
        if not isinstance(g, dict) or not g.get("name"):
            continue
        v[g["name"]] = "pass" if g.get("passed") is True else ("infra" if g.get("infra") else "fail")
    if (card or {}).get("reviewer_model"):
        models["doctrine"] = card["reviewer_model"]
    return v, models
