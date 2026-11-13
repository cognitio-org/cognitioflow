import re
from dataclasses import dataclass


FORBIDDEN_AI_HOSTS: list[str] = [
    "api.anthropic.com",
    "anthropic.com",
    "api.openai.com",
    "openai.com",
    "generativelanguage.googleapis.com",
    "api.cohere.ai",
    "router.kernal.one",
    "api.mistral.ai",
    "openrouter.ai",
]


@dataclass
class SelfContainedVerdict:
    ok: bool
    hits: list[str]


def check_self_contained(
    bundle_text: str, extra_forbidden: list[str] | None = None
) -> SelfContainedVerdict:
    try:
        forbidden_hosts = FORBIDDEN_AI_HOSTS + (extra_forbidden or [])
        matches: dict[tuple[int, int], str] = {}

        for host in forbidden_hosts:
            lowered_bundle = bundle_text.lower()
            lowered_host = host.lower()
            start = 0
            while True:
                start = lowered_bundle.find(lowered_host, start)
                if start == -1:
                    break
                matches[(start, start + len(host))] = host
                start += 1

        url_pattern = re.compile(
            r"https?://([a-zA-Z0-9.-]+)(?::[0-9]+)?(?:/[^\s\"'<>]*)?",
            re.IGNORECASE,
        )
        for match in url_pattern.finditer(bundle_text):
            url_host = match.group(1).lower()
            for host in forbidden_hosts:
                if url_host == host.lower():
                    host_start, host_end = match.span(1)
                    matches[(host_start, host_end)] = host
                    break

        hits = []
        for (start, end), host in sorted(matches.items()):
            context_start = max(0, start - 20)
            context_end = min(len(bundle_text), end + 20)
            context = bundle_text[context_start:context_end]
            hits.append(f"{host}: {context}")

        return SelfContainedVerdict(ok=not hits, hits=hits)
    except Exception as error:
        return SelfContainedVerdict(ok=False, hits=[f"scan error: {error}"])


def passes(
    bundle_text: str, extra_forbidden: list[str] | None = None
) -> bool:
    return not check_self_contained(bundle_text, extra_forbidden).hits
