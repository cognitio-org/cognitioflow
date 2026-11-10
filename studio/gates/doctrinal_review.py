import json
import re
from dataclasses import dataclass


@dataclass
class DoctrineVerdict:
    ok: bool
    issues: list[str]
    raw: str


def build_prompt(source_text: str, generated_text: str) -> str:
    return f"""Compare the GENERATED legal content against the authoritative SOURCE passage. Check that the generated text does not misstate or distort the doctrine in the source, including by inventing a legal rule, misstating an element, or reversing a rule.

SOURCE:
{source_text}

GENERATED:
{generated_text}

Return STRICT JSON only, in this format:
{{"ok": <bool>, "issues": [<short strings>]}}
Set "ok" to false if the generated text states a legal rule, element, or consequence that the source does not support. Otherwise set "ok" to true and "issues" to an empty list.
"""


def parse_verdict(raw: str) -> DoctrineVerdict:
    """Extract and validate the first JSON object, failing closed if it is unreadable."""
    json_match = re.search(
        r'\{(?:[^{}"]|"(?:\\.|[^"\\])*")*\}',
        raw,
        re.DOTALL,
    )
    if not json_match:
        return DoctrineVerdict(
            ok=False,
            issues=["unparseable reviewer output"],
            raw=raw,
        )

    try:
        data = json.loads(json_match.group(0))
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("ok"), bool)
            or not isinstance(data.get("issues"), list)
            or not all(isinstance(issue, str) for issue in data["issues"])
        ):
            raise ValueError("invalid reviewer verdict")
        return DoctrineVerdict(ok=data["ok"], issues=data["issues"], raw=raw)
    except (json.JSONDecodeError, ValueError):
        return DoctrineVerdict(
            ok=False,
            issues=["unparseable reviewer output"],
            raw=raw,
        )


def review_doctrine(source_text: str, generated_text: str, reviewer) -> DoctrineVerdict:
    """Review generated text against the source using the injected reviewer callable."""
    raw = reviewer(build_prompt(source_text, generated_text))
    return parse_verdict(raw)
