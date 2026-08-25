from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from investor_intel.indexing.loader import LoadedDocument, load_vault
from investor_intel.ingest.quality import is_corrupt, readable_ratio
from investor_intel.knowledge.registry import ANALYST_HOUSE, CompanyRegistry, load_dart_names
from investor_intel.knowledge.schema import Concept, EntityRef, Period, Provenance

# source_type -> (concept type, 번들 내 디렉터리)
_MAP = {
    "dart": ("DartFiling", "filings/dart"),
    "sec_filing": ("SecFiling", "filings/sec"),
    "sec_13f": ("HoldingsSnapshot", "holdings"),
    "telegram": ("MarketCommentary", "commentary"),
    "naver": ("BlogPost", "blog"),
    "ib_insights": ("ResearchNote", "research"),
    "essay": ("Essay", "essays"),
}

# concept type별 신선도 계약. OKF의 timestamp는 '언제 갱신됐나'만 말해주므로,
# '언제까지 유효하다고 볼 것인가'는 도메인이 정해야 한다.
_STALE_DAYS = {
    "DartFiling": 400, "SecFiling": 400, "HoldingsSnapshot": 120,
    "MarketCommentary": 90, "BlogPost": 365, "ResearchNote": 365, "Essay": 3650,
}

_SLUG = re.compile(r"[^a-z0-9가-힣]+")


def _ref_for(reg: CompanyRegistry, key: str) -> EntityRef | None:
    """frontmatter의 관계 키를 번들의 EntityRef로 되돌린다.

    레지스트리에 없는 키(사전에 있었지만 아직 concept으로 승격되지 않은 종목)는 사전에서
    승격해 링크 대상이 실제로 존재하게 만든다 - 그러지 않으면 끊어진 링크가 된다.

    수집기가 밝힌 종목은 시장 접두어 없이 코드만 온다(`028050`). 번들의 키는 시장을 붙인
    형태(`kr-028050`)이므로 접두어를 씌워 한 번 더 찾는다 - 그러지 않으면 그 관계가 조용히
    사라진다(실측: concept 11개, 링크 75개가 이 이유로 빠졌다).
    """
    for candidate in (key, f"kr-{key}", f"us-{key}"):
        company = reg.get(candidate) or reg.promote_key(candidate)
        if company is not None:
            return company.ref()
    return None


def slug(s: str) -> str:
    return _SLUG.sub("-", s.strip().lower()).strip("-") or "unknown"


# 수집기가 본문 맨 앞에 붙이는 정형 머리말. 제목·요약을 여기서 뽑으면
# 모든 문서 제목이 "원문 kyobofnbcosmetic (@kyobofnbcosmetic) — 2026-07-08T23:21:3"처럼 된다.
_PREAMBLE = re.compile(
    r"^\s*(?:##\s*원문\s*)?"
    r"(?:[^\n]*\(@[^\n]*\)\s*—\s*\d{4}-\d{2}-\d{2}T[^\n]*\n"
    r"|[^\n]*—\s*[^\n]*\(\d{4}-\d{2}-\d{2}[^\n]*\)\s*\n)?",
    re.M)


def lead_text(body: str) -> str:
    """머리말을 걷어낸 본문 앞부분."""
    t = _PREAMBLE.sub("", body.strip(), count=1).strip()
    return re.sub(r"^[\[\]\s*#]+", "", t)


def _first_sentence(text: str, limit: int = 110) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    t = re.sub(r"^#+ *", "", t)
    m = re.search(r"[.!?。]|다\.", t[:limit + 40])
    out = t[: m.end()] if m and m.end() <= limit + 40 else t[:limit]
    return out.strip()


_SEC_SUFFIX = re.compile(
    r"\s*(?:sponsored\s+)?(?:spn\.?)?\s*(?:adr(?:\s*\d+:\d+)?|reit|inc\.?|corp(?:oration)?\.?|"
    r"co\.?|ltd\.?|plc|llc|sa|nv|ag|holdings?|hldgs?|group|class\s+[a-c]|common|"
    r"pref|cl\s*[a-c])\b\.?", re.I)


def normalize_security(name: str) -> str:
    """13F 보고 명칭을 정규화한다.

    같은 종목이 'Alphabet Inc Class A', 'Alphabet Inc Class C'처럼 여러 이름으로 보고되고,
    같은 문서 안에서도 보유 건수만큼 반복된다. 이름만 있고 CUSIP/티커가 없으므로 완전한
    동일성 판정은 불가능하다 - 그래서 Company(식별자 있음)와 다른 Security 타입으로 둔다.
    """
    n = re.sub(r"[\u2018\u2019'\"]", "", name).strip()
    prev = None
    while prev != n:
        prev = n
        n = _SEC_SUFFIX.sub("", n).strip(" .,-")
    return (n or name.strip())[:60]


def _dedupe_holdings(names: list[str], limit: int = 30) -> list[str]:
    """13F의 companies는 같은 종목명이 보유 건수만큼 반복된다(예: 902종목 → 1,400개 문자열).
    지식 레이어에서는 종목 하나가 관계 하나여야 하므로 등장 순서를 유지하며 중복을 없앤다."""
    seen: dict[str, int] = {}
    for n in names:
        n = n.strip()
        if n:
            seen[n] = seen.get(n, 0) + 1
    return list(seen)[:limit]


def _describe(doc: LoadedDocument, ctype: str, subject: EntityRef | None,
              body: str) -> str:
    """concept의 description을 메타데이터에서 결정론적으로 만든다.

    OKF는 description을 사람이 읽는 한 줄 요약으로 요구하지만, 이 필드는 동시에
    Contextual Retrieval의 '청크 앞에 붙일 문맥'과 정확히 같은 역할을 한다.
    Anthropic 원안은 이 문장을 LLM으로 생성하고, 여기서는 확정된 메타데이터로 조립한다.
    """
    when = (doc.published_at or "")[:10]
    who = subject.name if subject else doc.source_name
    cap = "" if doc.capture_mode == "full" else " (본문 미확보, 링크만 보유)"
    if ctype == "DartFiling":
        base = f"{who}가 {when} DART에 접수한 {doc.filing_type or '공시'}"
        if doc.reporting_period:
            base += f". 보고 기준일 {doc.reporting_period[:10]}"
        return base + cap
    if ctype == "SecFiling":
        base = f"{who}가 {when} SEC에 제출한 {doc.filing_type or '공시'}"
        if doc.reporting_period:
            base += f". 보고 기준일 {doc.reporting_period[:10]}"
        return base + cap
    if ctype == "HoldingsSnapshot":
        return (f"{who}의 {(doc.reporting_period or when)[:10]} 기준 13F 보유 현황"
                f" (제출일 {when})") + cap
    if ctype == "MarketCommentary":
        return f"텔레그램 채널 {who}의 {when} 메시지. " + _first_sentence(lead_text(body))
    if ctype == "BlogPost":
        return f"{doc.author or who} 블로그 {when} 글 「{doc.title or '제목 없음'}」. " + _first_sentence(lead_text(body))
    if ctype == "ResearchNote":
        return f"{who}의 {when} 리서치 「{doc.title or '제목 없음'}」" + (cap or ". " + _first_sentence(lead_text(body)))
    return f"{who}, {when}. {doc.title or ''}".strip() + cap


def _tags(doc: LoadedDocument, ctype: str, subject: EntityRef | None) -> list[str]:
    t = [doc.source_type]
    if doc.filing_type:
        t.append(doc.filing_type)
    if subject:
        t.append(subject.key)
    if doc.language:
        t.append(doc.language)
    if doc.capture_mode != "full":
        t.append(doc.capture_mode)
    return list(dict.fromkeys(t))[:8]


def _stale_after(ctype: str, published: str | None) -> str | None:
    if not published or len(published) < 10:
        return None
    try:
        d = date.fromisoformat(published[:10])
    except ValueError:
        return None
    return (d + timedelta(days=_STALE_DAYS.get(ctype, 365))).isoformat()


def build_concepts(vault: Path, db_path: Path) -> tuple[list[Concept], CompanyRegistry, dict]:
    reg = CompanyRegistry()
    dart_names = load_dart_names(db_path)
    stats: dict = {"by_type": Counter(), "status": Counter(),
                   "mentions_recovered": 0, "mentions_from_frontmatter": 0,
                   "analyst_houses_split": 0, "docs_with_subject": 0, "corrupt": 0,
                   "duplicate_ids_skipped": 0, "superseded": 0}

    docs: list[LoadedDocument] = []
    seen: set[str] = set()
    for d in load_vault(vault, strip_boilerplate=True):
        if d.doc_id in seen:
            stats["duplicate_ids_skipped"] += 1
            continue
        seen.add(d.doc_id)
        docs.append(d)

    # --- 1단계: 엔티티 레지스트리를 먼저 세운다 ------------------------------
    # 상장법인 명부를 '매칭 사전'으로만 올린다. 언급된 종목만 나중에 concept이 된다.
    for code, name in dart_names.items():
        reg.add_lexicon(name, "kr", code)

    investors: dict[str, str] = {}
    channels: dict[str, tuple[str, str]] = {}
    securities: dict[str, str] = {}
    for d in docs:
        if d.source_type == "dart":
            code = d.source_name
            name = d.author or dart_names.get(code) or code
            reg.add(f"kr-{code}", name, "kr", code, aliases=[dart_names.get(code, "")])
        elif d.source_type == "sec_filing":
            reg.add(f"us-{d.source_name}", d.author or d.source_name, "us", d.source_name)
        elif d.source_type == "sec_13f":
            investors[f"inv-{slug(d.source_name)}"] = d.author or d.source_name
        else:
            kind = {"telegram": "telegram", "naver": "naver", "ib_insights": "ib",
                    "essay": "essay"}[d.source_type]
            channels[f"ch-{kind}-{slug(d.source_name)}"] = (d.author or d.source_name, kind)

    concepts: list[Concept] = []

    # --- 2단계: 허브 concept (투자자·채널) ----------------------------------
    for key, name in investors.items():
        concepts.append(Concept(type="Investor", title=name,
            description=f"{name}의 13F 보유 현황 스냅샷이 이 파일로 연결된다.",
            tags=["13f"], key=key, folder="investors",
            timestamp=datetime.now().replace(microsecond=0).isoformat() + "Z"))
    for key, (name, kind) in channels.items():
        concepts.append(Concept(type="SourceChannel", title=name,
            description=f"{name} ({kind}) 발행 문서가 이 파일로 연결된다.",
            tags=[kind], key=key, folder="sources",
            timestamp=datetime.now().replace(microsecond=0).isoformat() + "Z"))

    # --- 3단계: 문서 concept ------------------------------------------------
    version_groups: dict[tuple, list[Concept]] = defaultdict(list)
    for d in docs:
        ctype, folder = _MAP[d.source_type]
        subject: EntityRef | None = None
        mentions: list[EntityRef] = []
        houses: list[EntityRef] = []
        if d.source_type == "dart":
            subject = reg.by_key[f"kr-{d.source_name}"].ref()
        elif d.source_type == "sec_filing":
            subject = reg.by_key[f"us-{d.source_name}"].ref()
        elif d.source_type == "sec_13f":
            key = f"inv-{slug(d.source_name)}"
            subject = EntityRef("investor", key, investors[key])
            for nm in _dedupe_holdings(d.companies, limit=40):
                norm = normalize_security(nm)
                mentions.append(EntityRef("security", f"sec-{slug(norm)}", norm))
                securities[f"sec-{slug(norm)}"] = norm
        else:
            kind = {"telegram": "telegram", "naver": "naver", "ib_insights": "ib",
                    "essay": "essay"}[d.source_type]
            key = f"ch-{kind}-{slug(d.source_name)}"
            subject = EntityRef("channel", key, channels[key][0])
            # 수집 시점에 이미 해소된 관계가 있으면 그것을 쓴다. 같은 판정을 여기서 다시
            # 하면 사전이 달라진 순간 frontmatter와 번들이 서로 다른 답을 갖게 된다.
            if d.mentions or d.analyst_house:
                mentions = [_ref_for(reg, key) for key in d.mentions]
                houses = [_ref_for(reg, key) for key in d.analyst_house]
                mentions = [m for m in mentions if m is not None]
                houses = [h for h in houses if h is not None]
                stats["mentions_from_frontmatter"] += len(mentions)
            else:
                found = reg.find_mentions(d.body, limit=10)
                mentions = [m for m in found if not ANALYST_HOUSE.search(m.name)]
                houses = [m for m in found if ANALYST_HOUSE.search(m.name)]
                stats["mentions_recovered"] += len(mentions)
            stats["analyst_houses_split"] += len(houses)

        period = Period(published=(d.published_at or "")[:10] or None,
                        as_of=(d.reporting_period or "")[:10] or None)
        if period.as_of and len(period.as_of) == 10:
            q = (int(period.as_of[5:7]) - 1) // 3 + 1
            period.fiscal = f"{period.as_of[:4]}-Q{q}"

        # 가독 비율은 수집 시점에 측정돼 frontmatter에 있다. 없으면(옛 문서) 원문에서
        # 직접 잰다 - `enrich-vault`를 돌리면 이 폴백이 필요 없어진다.
        ratio_ok = d.readable_ratio
        if ratio_ok == 1.0:
            raw_body = Path(d.path).read_text(encoding="utf-8")
            ratio_ok = readable_ratio(raw_body)
        quality = None
        status = "stub" if d.capture_mode == "metadata_only" else "stable"
        if is_corrupt(ratio_ok):
            status = "corrupt"
            quality = {"readable_ratio": round(ratio_ok, 3),
                       "flags": ["encoding_corrupt"],
                       "note": "원본 저장 시점에 인코딩이 깨져 본문을 신뢰할 수 없다. "
                               "재수집 전까지 근거로 인용하지 말 것."}
            stats["corrupt"] += 1
        c = Concept(
            type=ctype,
            title=(d.title or _first_sentence(lead_text(d.body), 60)
                   or f"{d.source_name} {period.published}"),
            description=_describe(d, ctype, subject, d.body),
            resource=d.source_url,
            tags=_tags(d, ctype, subject),
            timestamp=(d.published_at or ""),
            key=f"{(period.published or 'undated')}-{d.doc_id[:10]}",
            folder=folder, status=status, language=d.language, capture=d.capture_mode,
            period=period, stale_after=_stale_after(ctype, period.published),
            subject=subject, mentions=mentions, analyst_houses=houses, quality=quality,
            provenance=Provenance(system=d.source_type, native_id=d.accession_number,
                                  collected_at="", content_hash=d.doc_id,
                                  source_path=d.path),
            body=d.body,
        )
        if subject:
            stats["docs_with_subject"] += 1
        concepts.append(c)
        if ctype in ("DartFiling", "SecFiling") and subject and d.filing_type and period.as_of:
            version_groups[(subject.key, d.filing_type, period.as_of)].append(c)

    for key, name in securities.items():
        concepts.append(Concept(
            type="Security", title=name,
            description=f"{name}. 13F 보고서에 보유 종목으로 등장한 명칭이며 티커·CUSIP은 "
                        f"이 번들에서 확정하지 않았다. 이 종목을 보유한 기관의 스냅샷이 여기로 연결된다.",
            tags=["13f", "holding"], key=key, folder="securities",
            timestamp=datetime.now().replace(microsecond=0).isoformat() + "Z"))

    # 회사 허브는 문서 처리가 끝난 뒤에 만든다 - 본문에서 승격된 종목까지 포함해야
    # 마크다운 링크의 대상 파일이 모두 존재하기 때문이다.
    for c in reg.by_key.values():
        concepts.append(Concept(
            type="Company", title=c.name,
            description=f"{c.name} ({'KRX ' if c.market == 'kr' else ''}{c.code}). "
                        f"이 종목을 다루는 공시·리서치·시장 코멘트가 이 파일로 연결된다.",
            resource=(f"https://finance.naver.com/item/main.naver?code={c.code}"
                      if c.market == "kr" else f"https://www.sec.gov/cgi-bin/browse-edgar?ticker={c.code}"),
            tags=[c.market, c.code], key=c.key, folder="companies",
            timestamp=datetime.now().replace(microsecond=0).isoformat() + "Z"))

    # --- 4단계: 같은 기준일·같은 유형의 재제출은 supersede 관계로 표시 -------
    for group in version_groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda c: c.period.published or "")
        latest = group[-1]
        for old in group[:-1]:
            old.status = "superseded"
            old.extra_links.append(("대체 문서", f"[{latest.title}]({latest.key}.md)"))
            stats["superseded"] += 1

    for c in concepts:
        stats["by_type"][c.type] += 1
        stats["status"][c.status] += 1
    return concepts, reg, stats


def build_bundle(vault: Path, db_path: Path, out_root: Path) -> dict:
    concepts, reg, stats = build_concepts(vault, db_path)
    out_root.mkdir(parents=True, exist_ok=True)

    by_folder: dict[str, list[Concept]] = defaultdict(list)
    written = 0
    for c in concepts:
        d = out_root / c.folder
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{c.key}.md").write_text(c.render(), encoding="utf-8")
        by_folder[c.folder].append(c)
        written += 1

    # OKF: 디렉터리마다 index.md를 둬 에이전트가 계층을 점진적으로 탐색하게 한다.
    for folder, items in by_folder.items():
        items.sort(key=lambda c: c.key, reverse=True)
        lines = [f"---\ntype: Index\ntitle: {folder}\n"
                 f"description: {folder} 아래 concept {len(items)}건의 목록\n---\n",
                 f"# {folder}\n", f"concept {len(items)}건.\n"]
        shown = items[:200]
        for c in shown:
            flag = "" if c.status == "stable" else f" `{c.status}`"
            lines.append(f"- [{c.title[:70]}]({c.key}.md) — {c.type}{flag}")
        if len(items) > len(shown):
            lines.append(f"\n_외 {len(items) - len(shown)}건은 파일 시스템에서 직접 탐색._")
        (out_root / folder / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    root_lines = ["---", "type: Bundle", "title: Investor Intelligence Knowledge Bundle",
                  "description: 투자정보 수집 vault(10_Sources)에서 파생한 OKF 지식 레이어.",
                  f"timestamp: {datetime.now().replace(microsecond=0).isoformat()}Z",
                  "---", "", "# Investor Intelligence Knowledge Bundle", "",
                  "원본은 `vault/10_Sources/`에 증거로 그대로 보존되고, 이 번들은 거기서 파생한",
                  "지식 레이어다. concept 하나가 파일 하나이며, 관계는 마크다운 링크로 표현된다.", "",
                  "## 디렉터리", ""]
    for folder in sorted(by_folder):
        root_lines.append(f"- [{folder}]({folder}/index.md) — {len(by_folder[folder])}건")
    root_lines += ["", "## 타입별 concept 수", ""]
    for t, n in stats["by_type"].most_common():
        root_lines.append(f"- `{t}` {n:,}")
    root_lines += ["", "## status", ""]
    for s, n in stats["status"].most_common():
        root_lines.append(f"- `{s}` {n:,}")
    (out_root / "index.md").write_text("\n".join(root_lines) + "\n", encoding="utf-8")

    (out_root / "log.md").write_text(
        "---\ntype: Log\ntitle: 변경 이력\ndescription: 번들 생성·갱신 기록\n---\n\n"
        f"- {datetime.now().replace(microsecond=0).isoformat()}Z — "
        f"vault/10_Sources에서 최초 생성. concept {written:,}건 "
        f"(허브 {sum(1 for c in concepts if c.type in ('Company','Investor','SourceChannel')):,}, "
        f"문서 {sum(1 for c in concepts if c.type not in ('Company','Investor','SourceChannel')):,}). "
        f"중복 id {stats['duplicate_ids_skipped']}건 스킵, "
        f"supersede {stats['superseded']}건 표시, "
        f"원본에 없던 종목 관계 {stats['mentions_recovered']:,}건 복원, "
        f"그중 분석 주체(증권사·운용사) {stats['analyst_houses_split']:,}건은 별도 관계로 분리.\n",
        encoding="utf-8")

    return {"written": written, "folders": {k: len(v) for k, v in by_folder.items()},
            "by_type": dict(stats["by_type"]), "status": dict(stats["status"]),
            "mentions_recovered": stats["mentions_recovered"],
            "mentions_from_frontmatter": stats["mentions_from_frontmatter"],
            "analyst_houses_split": stats["analyst_houses_split"],
            "docs_with_subject": stats["docs_with_subject"],
            "duplicate_ids_skipped": stats["duplicate_ids_skipped"],
            "superseded": stats["superseded"], "corrupt": stats["corrupt"],
            "companies": len(reg.by_key)}
