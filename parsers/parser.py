"""parser.py

Compact parsing module (splits kept to minimum per feedback).
Handles YAML‑driven parsing for **all** parts; no extra helper utilities are
exported – just `GenericParser`.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set

import yaml

__all__ = ["GenericParser"]

# ──────────────────────────────── configuration paths ───────────────────────────────── #
BASE_DIR: Path = Path(__file__).resolve().parents[1]
CONFIG_PATH: Path = BASE_DIR / "parsers" / "parser_rules.yaml"

# fields that stay at top level when writing JSON
_TOP_LEVEL_FIELDS: Set[str] = {
    "id",
    "name",
    "image_url",
    "price",
    "in_stock",
    "product_url",
}

# 파싱 할 부품 정보
parts = [
    "CPU",
    "Cooler",
    "Motherboard",
    "Memory",
    "VGA",
    "SSD",
    "HDD",
    "Case",
    "PSU",
]

# ───────────────────────────────────── parser class ──────────────────────────────────── #
class GenericParser:
    """YAML‑rule based parser; returns a flat dict of parsed fields."""

    _compiled: Dict[str, List[tuple[str, re.Pattern[str], list[int] | int]]] = {}

    def __init__(self, config_path: Path | str = CONFIG_PATH) -> None:
        # YAML 읽기 – 별도 함수로 빼지 않고 한 줄로 처리
        with Path(config_path).open(encoding="utf-8") as fp:
            self.cfg: Dict[str, Any] = yaml.safe_load(fp)

        # name_rules 정규식 선‑컴파일
        for cat, meta in self.cfg.items():
            self._compiled[cat] = [
                (
                    rule["key"],
                    re.compile(rule["regex"]),
                    rule.get("group", 1),
                )
                for rule in meta.get("name_rules", [])
            ]

    # public -----------------------------------------------------------------
    def parse(self, category: str, row: Mapping[str, str]) -> Dict[str, Any]:
        if category not in self.cfg:
            raise ValueError(f"No config for category '{category}'")
        rules = self.cfg[category]
        return {
            "id": int(row["ID"]),
            **self._parse_name(row["Name"], category),
            **self._parse_spec(row.get("Spec", ""), rules.get("spec", {})),
            "image_url": row.get("ImageURL"),
            "product_url": row.get("ProductURL"),
        }

    # internal ---------------------------------------------------------------
    def _parse_name(self, text: str, category: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key, pattern, grp in self._compiled.get(category, []):
            if m := pattern.search(text):
                out[key] = (
                    " ".join(m.group(i) for i in grp).strip() if isinstance(grp, list) else m.group(grp).strip()
                )
        return out

    def _parse_spec(self, spec: str, rules: Dict[str, Any]) -> Dict[str, Any]:
        spec = self._preprocess(spec)
        segments = self._split_segments(spec)
        return self._apply_rules(segments, rules)

    # helpers ---------------------------------------------------------------
    @staticmethod
    def _preprocess(txt: str) -> str:
        repl = {
            "A/S": "AS",
            "S/W": "SW",
            "Gb/s": "Gbs",
            "MB/s": "Mbs",
            "싱글/다중": "싱글,다중",
        }
        for a, b in repl.items():
            txt = txt.replace(a, b)
        if "유휴/탐색" in txt and "소음(" in txt:
            s, e = txt.find("소음("), txt.rfind("dB") + 2
            txt = txt[:s] + txt[s:e].replace("/", ",") + txt[e:]
        if "순차읽기" in txt:
            for tag in ("순차읽기:", "순차쓰기:", "읽기IOPS:", "쓰기IOPS:"):
                txt = txt.replace(tag, tag[:-1])
        return txt

    @staticmethod
    def _split_segments(spec: str) -> List[str]:
        outer = " ".join(re.split(r"\[[^]]*]", spec))
        return [s.strip() for seg in outer.split("/") if (s := seg.strip())]

    def _apply_rules(self, segments: List[str], rules: Dict[str, Any]) -> Dict[str, Any]:
        res: Dict[str, Any] = {}
        colon_cfg = rules.get("colon_keys", {})
        # ① colon‑style
        for seg in (s for s in segments if ":" in s):
            k_raw, v_raw = (t.strip() for t in seg.split(":", 1))
            if k_raw in colon_cfg:
                ek = colon_cfg[k_raw]
                res[ek] = [v.strip() for v in v_raw.split(",")] if "," in v_raw else v_raw.strip()
        # ② pattern‑style
        for seg in (s for s in segments if ":" not in s):
            for pat in rules.get("non_colon_patterns", []):
                if not self._matches(seg, pat):
                    continue
                self._apply_pat(res, seg, pat)
        return res

    # pattern helpers -------------------------------------------------------
    @staticmethod
    def _matches(seg: str, pat: Dict[str, Any]) -> bool:
        return any(
            (
                "contains" in pat and pat["contains"] in seg,
                "contains_any" in pat and any(c in seg for c in pat["contains_any"]),
                "endswith" in pat and seg.endswith(pat["endswith"]),
                "regex" in pat and re.search(pat["regex"], seg),
            )
        )

    @staticmethod
    def _apply_pat(out: Dict[str, Any], seg: str, pat: Dict[str, Any]) -> None:
        key = pat["key"]
        if "extract_all" in pat:
            out[key] = re.findall(pat["extract_all"], seg)
        elif "extract" in pat and (m := re.search(pat["extract"], seg)):
            out[key] = m.group(1)
        elif "groups" in pat and (m := re.search(pat["regex"], seg)):
            gs = pat["groups"]
            out[key] = m.group(gs[0]) if len(gs) == 1 else [m.group(i) for i in gs]
        elif "split_on" in pat:
            out[key] = [x.strip() for x in seg.split(pat["split_on"])]
        else:
            out[key] = seg

# ─────────────────────────── simple demo: parse all parts ────────────────────────────── #
if __name__ == "__main__":
    parser = GenericParser()
    parsed_dir = BASE_DIR / "data" / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)

    for part in parts:
        src_path = BASE_DIR / "data" / "raw" / part / f"{part}_info_clean.csv"
        dest_path = parsed_dir / f"{part}_parsed.json"
        records: List[Dict[str, Any]] = []
        with src_path.open(encoding="utf-8") as fp:
            for row in csv.DictReader(fp):
                flat = parser.parse(part, row)
                grouped = {
                    **{k: flat[k] for k in _TOP_LEVEL_FIELDS if k in flat},
                    "spec": {k: v for k, v in flat.items() if k not in _TOP_LEVEL_FIELDS},
                }
                records.append(grouped)
        dest_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{part} → {dest_path.relative_to(BASE_DIR)}")
