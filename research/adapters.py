"""Turning each API's reply into one record shape.

One function per source format, all with the same signature: `(payload, source) -> list[Record]`.
Nothing here touches the network, so every adapter is testable against a saved fixture — which
is the only way to keep a harvester honest when the upstream shape drifts.

An adapter that cannot find a field leaves it empty. It never invents one. A record with no
date is a record Lector will rank last, which is the correct outcome for a source that stopped
telling us when things were published.
"""

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field

ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass
class Record:
    """One thing that was published somewhere, normalised."""

    uid: str            # stable across runs: how Lector knows it has seen this before
    source_id: str
    track: str
    kind: str
    title: str
    url: str = ""
    date: str = ""      # ISO date, "" when the source did not say
    authors: tuple = field(default_factory=tuple)
    abstract: str = ""
    venue: str = ""
    doi: str = ""
    authority: int = 5
    score: float = 0.0
    flags: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return asdict(self)


def _clean(text: str) -> str:
    """Collapse the whitespace that XML abstracts arrive wrapped in."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def _iso(value: str) -> str:
    """Keep the date part of whatever the source called a timestamp."""
    if not value:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return m.group(1) if m else ""


def _record(source, uid: str, title: str, **kw) -> Record:
    return Record(
        uid=f"{source.id}:{uid}",
        source_id=source.id,
        track=source.track,
        kind=source.kind,
        authority=source.authority,
        title=_clean(title),
        **kw,
    )


# ------------------------------------------------------------------ paper sources

def arxiv(payload: bytes, source) -> list:
    """arXiv returns Atom. Entry id doubles as the canonical URL."""
    root = ET.fromstring(payload)
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        arxiv_id = _clean(entry.findtext(f"{ATOM}id", ""))
        if not arxiv_id:
            continue
        out.append(_record(
            source,
            uid=arxiv_id.rsplit("/", 1)[-1],
            title=entry.findtext(f"{ATOM}title", ""),
            url=arxiv_id,
            date=_iso(entry.findtext(f"{ATOM}published", "")),
            authors=tuple(
                _clean(a.findtext(f"{ATOM}name", "")) for a in entry.findall(f"{ATOM}author")
            ),
            abstract=_clean(entry.findtext(f"{ATOM}summary", "")),
            venue="arXiv",
        ))
    return out


def openalex(payload: bytes, source) -> list:
    """OpenAlex inverts its abstracts to dodge copyright; put them back in word order."""
    out = []
    for work in json.loads(payload).get("results", []):
        wid = work.get("id", "")
        if not wid:
            continue
        host = (work.get("primary_location") or {}).get("source") or {}
        out.append(_record(
            source,
            uid=wid.rsplit("/", 1)[-1],
            title=work.get("display_name") or work.get("title") or "",
            url=work.get("doi") or wid,
            date=_iso(work.get("publication_date", "")),
            authors=tuple(
                _clean((a.get("author") or {}).get("display_name", ""))
                for a in (work.get("authorships") or [])[:8]
            ),
            abstract=_deinvert(work.get("abstract_inverted_index")),
            venue=_clean(host.get("display_name", "")),
            doi=_clean((work.get("doi") or "").replace("https://doi.org/", "")),
        ))
    return out


def _deinvert(index) -> str:
    """{'word': [3, 9]} back into a sentence. OpenAlex's abstract format."""
    if not index:
        return ""
    slots = {}
    for word, positions in index.items():
        for p in positions:
            slots[p] = word
    if not slots:
        return ""
    return _clean(" ".join(slots[k] for k in sorted(slots)))


def crossref(payload: bytes, source) -> list:
    out = []
    for item in json.loads(payload).get("message", {}).get("items", []):
        doi = item.get("DOI", "")
        if not doi:
            continue
        title = (item.get("title") or [""])[0]
        out.append(_record(
            source,
            uid=doi,
            title=title,
            url=item.get("URL") or f"https://doi.org/{doi}",
            date=_iso(_crossref_date(item)),
            authors=tuple(
                _clean(f"{a.get('given', '')} {a.get('family', '')}")
                for a in (item.get("author") or [])[:8]
            ),
            abstract=_clean(re.sub(r"<[^>]+>", " ", item.get("abstract", ""))),
            venue=_clean((item.get("container-title") or [""])[0]),
            doi=doi,
        ))
    return out


def _crossref_date(item) -> str:
    """Crossref date-parts: [[2026, 9, 19]]. Any of three fields may carry it."""
    for key in ("published-print", "published-online", "created"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            y, m, d = (list(parts[0]) + [1, 1])[:3]
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return ""


def doaj(payload: bytes, source) -> list:
    out = []
    for hit in json.loads(payload).get("results", []):
        bib = hit.get("bibjson") or {}
        uid = hit.get("id", "")
        if not uid:
            continue
        links = bib.get("link") or []
        out.append(_record(
            source,
            uid=uid,
            title=bib.get("title", ""),
            url=next((link.get("url", "") for link in links if link.get("url")), ""),
            date=_iso(str(bib.get("year", ""))) or (f"{bib['year']}-01-01" if bib.get("year") else ""),
            authors=tuple(_clean(a.get("name", "")) for a in (bib.get("author") or [])[:8]),
            abstract=_clean(bib.get("abstract", "")),
            venue=_clean((bib.get("journal") or {}).get("title", "")),
        ))
    return out


# ------------------------------------------------------------------ public record sources

def federal_register(payload: bytes, source) -> list:
    out = []
    for doc in json.loads(payload).get("results", []):
        num = doc.get("document_number", "")
        if not num:
            continue
        out.append(_record(
            source,
            uid=num,
            title=doc.get("title", ""),
            url=doc.get("html_url", ""),
            date=_iso(doc.get("publication_date", "")),
            abstract=_clean(doc.get("abstract", "")),
            venue=_clean(", ".join(a.get("name", "") for a in (doc.get("agencies") or [])[:3])),
        ))
    return out


def courtlistener(payload: bytes, source) -> list:
    out = []
    for hit in json.loads(payload).get("results", []):
        uid = str(hit.get("id") or hit.get("cluster_id") or "")
        if not uid:
            continue
        path = hit.get("absolute_url", "")
        out.append(_record(
            source,
            uid=uid,
            title=hit.get("caseName") or hit.get("case_name") or "",
            url=f"https://www.courtlistener.com{path}" if path.startswith("/") else path,
            date=_iso(hit.get("dateFiled") or hit.get("date_filed") or ""),
            abstract=_clean(hit.get("snippet", "")),
            venue=_clean(hit.get("court", "")),
        ))
    return out


def rechtspraak(payload: bytes, source) -> list:
    """Rechtspraak's search endpoint returns Atom with an ECLI as the entry id."""
    root = ET.fromstring(payload)
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        ecli = _clean(entry.findtext(f"{ATOM}id", ""))
        if not ecli:
            continue
        link = entry.find(f"{ATOM}link")
        out.append(_record(
            source,
            uid=ecli.rsplit("/", 1)[-1],
            title=entry.findtext(f"{ATOM}title", "") or ecli,
            url=(link.get("href") if link is not None else "") or ecli,
            date=_iso(entry.findtext(f"{ATOM}updated", "")),
            abstract=_clean(entry.findtext(f"{ATOM}summary", "")),
            venue="Rechtspraak.nl",
        ))
    return out


def gleif(payload: bytes, source) -> list:
    out = []
    for rec in json.loads(payload).get("data", []):
        lei = rec.get("id", "")
        if not lei:
            continue
        entity = (rec.get("attributes") or {}).get("entity") or {}
        legal = entity.get("legalAddress") or {}
        out.append(_record(
            source,
            uid=lei,
            title=(entity.get("legalName") or {}).get("name", "") or lei,
            url=f"https://search.gleif.org/#/record/{lei}",
            date=_iso(((rec.get("attributes") or {}).get("registration") or {}).get("lastUpdateDate", "")),
            abstract=_clean(
                f"{entity.get('status', '')} · {legal.get('country', '')} · LEI {lei}"
            ),
            venue="GLEIF",
        ))
    return out


def sec_submissions(payload: bytes, source) -> list:
    """One CIK's recent filings. The reply nests parallel arrays, not objects."""
    data = json.loads(payload)
    recent = (data.get("filings") or {}).get("recent") or {}
    name = data.get("name", "")
    cik = str(data.get("cik", "")).zfill(10)
    accessions = recent.get("accessionNumber") or []
    out = []
    for i, accession in enumerate(accessions):
        def at(key, idx=i):
            seq = recent.get(key) or []
            return seq[idx] if idx < len(seq) else ""
        doc = at("primaryDocument")
        plain = accession.replace("-", "")
        out.append(_record(
            source,
            uid=accession,
            title=f"{name} — {at('form')} {at('primaryDocDescription') or ''}".strip(" —"),
            url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{plain}/{doc}" if doc else "",
            date=_iso(at("filingDate")),
            abstract=_clean(f"Form {at('form')} filed {at('filingDate')}, period {at('reportDate')}"),
            venue="SEC EDGAR",
        ))
    return out


ADAPTERS = {
    "arxiv": arxiv,
    "openalex": openalex,
    "crossref": crossref,
    "doaj": doaj,
    "federal_register": federal_register,
    "courtlistener": courtlistener,
    "rechtspraak": rechtspraak,
    "gleif": gleif,
    "sec_submissions": sec_submissions,
}
