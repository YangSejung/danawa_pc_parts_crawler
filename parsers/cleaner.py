"""dataset_cleaner.py

Remove unwanted rows (e.g. overseas models, used/refurbished listings, server‑grade
CPUs) from *raw* CSV files before they enter the parsing pipeline.

Rationale for the filename
──────────────────────────
* `dataset_cleaner` conveys **scope** (entire dataset) and **purpose** (cleaning).
  - `raw_filter.py` or `data_sanitizer.py`도 가능하지만, *cleaner*가 더 직관적.

Design goals
────────────
• **Config‑driven** – 키워드·정규식·컬럼명 등을 YAML/JSON으로 빼 유지보수 용이
• **Stateless** – 어떤 CSV를 주어도 입력‑>출력만, 글로벌 변수 최소화
• **CLI** – 파트(카테고리)·입출력 디렉터리 지정 가능
• **Fast** – Pandas 벡터라이즈드 필터 사용
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml

# ─────────────────────────────── default paths & config ─────────────────────────────── #
ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
CONF_PATH = ROOT / "parsers" / "clean_rules.yaml"

# ─────────────────────────────── load filter rules ──────────────────────────────────── #

def _load_rules(path: Path) -> Dict[str, Dict[str, List[str]]]:
    """YAML structure example:
    CPU:
      drop_if_name_contains: [해외, 중고]
      drop_if_name_regex:    ['Xeon', 'EPYC', 'Opteron']
    VGA:
      drop_if_name_contains: [해외]
    """
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)

# ─────────────────────────────── cleaner core ───────────────────────────────────────── #

def clean_csv(csv_path: Path, out_path: Path, rules: Dict[str, List[str]]):
    df = pd.read_csv(csv_path)
    name_col = "Name" if "Name" in df.columns else df.columns[1]  # fallback

    contains = rules.get("drop_if_name_contains", [])
    regexes  = [re.compile(r, re.I) for r in rules.get("drop_if_name_regex", [])]

    mask = pd.Series(False, index=df.index)

    # contains 조건
    if contains:
        pattern = re.compile("|".join(map(re.escape, contains)), re.I)
        mask |= df[name_col].str.contains(pattern)

    # regex 조건
    for rgx in regexes:
        mask |= df[name_col].str.contains(rgx)

    removed = mask.sum()
    df_filtered = df[~mask]
    df_filtered.to_csv(out_path, index=False)
    print(f" {csv_path.name}: removed {removed} rows → {out_path.name}")

# ─────────────────────────────── cli orchestrator ──────────────────────────────────── #

def run_clean(parts: List[str], raw_dir: Path, out_dir: Path, conf: Path):
    rules = _load_rules(conf)
    out_dir.mkdir(parents=True, exist_ok=True)

    for part in parts:
        csv_in  = raw_dir / part / f"{part}_info.csv"
        csv_out = out_dir / part / f"{part}_info_clean.csv"
        csv_out.parent.mkdir(parents=True, exist_ok=True)

        part_rules = rules.get(part, {})
        if not part_rules:
            print(f"[!] No rules defined for {part}; copying without changes")
            csv_out.write_bytes(csv_in.read_bytes())
            continue

        clean_csv(csv_in, csv_out, part_rules)

# ─────────────────────────────────── entrypoint ─────────────────────────────────────── #

if __name__ == "__main__":
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

    ap = argparse.ArgumentParser(description="Clean raw CSV files based on name filters")
    ap.add_argument("--parts", nargs="*",
                    default=parts, help="Part categories to clean")
    ap.add_argument("--raw", type=Path, default=RAW_DIR, help="Input raw data directory")
    ap.add_argument("--out", type=Path, default=RAW_DIR, help="Output directory (default: in‑place)")
    ap.add_argument("--conf", type=Path, default=CONF_PATH, help="YAML filter rule file")
    args = ap.parse_args()

    run_clean(args.parts, args.raw, args.out, args.conf)
