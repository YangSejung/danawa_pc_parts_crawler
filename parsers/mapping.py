"""
가격·재고 정보 + (CPU/VGA) 벤치 점수 매핑 스크립트
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pandas as pd

# ──────────────────────────────── paths & constants ────────────────────────────────── #
DEF_ROOT = Path(__file__).resolve().parents[1]

PARTS = [
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

CPU_BENCH_COL_MAP = {
    "Cinebench R23 (Single-Core)": "cinebench_r23_single",
    "Cinebench R23 (Multi-Core)":  "cinebench_r23_multi",
    "Geekbench 6 (Single-Core)":   "geekbench6_single",
    "Geekbench 6 (Multi-Core)":    "geekbench6_multi",
    "Blender CPU":                 "blender_cpu",
}

GPU_BENCH_COL_MAP = {
    "Steel Nomad Lite Score":      "3d_mark",
    "GB6 Compute Score":           "geekbench6_opencl",
    "Blender GPU":                 "blender_gpu",
    "Average FPS by 1080p High":   "average_fps_by_1080p_high",
    "Average FPS by 1080p Ultra":  "average_fps_by_1080p_ultra",
    "Average FPS by 1440p Ultra":  "average_fps_by_1440p_ultra",
    "Average FPS by 4K Ultra":     "average_fps_by_4k_high",
}

_REMOVE_WORDS  = ("AMD", "인텔", "시리즈2")
_REPLACE_MAP   = {"Core": "코어", "Ryzen": "라이젠", "Ultra": "울트라"}
_REMOVE_PATTERN = re.compile("|".join(map(re.escape, _REMOVE_WORDS)))

# ──────────────────────────────── util helpers ─────────────────────────────────────── #
def _load_json(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))

def _save_json(data: List[Dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ───────────────────────── price / stock helpers ───────────────────────────────────── #
def _load_price_map(csv_path: Path) -> Dict[int, int]:
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path, dtype={"ID": "int64", "Price": "string"})
    df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
    return (
        df.dropna(subset=["Price"])
          .astype({"Price": "int64"})
          .set_index("ID")["Price"]
          .to_dict()
    )

def _update_price_stock(products: List[Dict[str, Any]], price_map: Mapping[int, int]) -> None:
    for p in products:
        pid = p.get("id")
        p["price"]    = price_map.get(pid)
        p["in_stock"] = pid in price_map

# ───────────────────────────── benchmark helpers ───────────────────────────────────── #
def _norm_series(series: pd.Series) -> pd.Series:
    s = series.str.replace(_REMOVE_PATTERN, "", regex=True)
    for src, dst in _REPLACE_MAP.items():
        s = s.str.replace(src, dst, regex=False)
    return s.str.replace(r"\s+", "", regex=True)

def _ensure_cols(df: pd.DataFrame, cols: List[str]) -> None:
    for c in cols:
        if c not in df.columns:
            df[c] = 0

def _load_cpu_bench_map(csv_path: Path) -> Dict[str, Dict[str, int]]:
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path)
    _ensure_cols(df, list(CPU_BENCH_COL_MAP.keys()))
    df = df[["name", *CPU_BENCH_COL_MAP]].rename(columns=CPU_BENCH_COL_MAP)
    num_cols = list(CPU_BENCH_COL_MAP.values())
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)
    df["norm_name"] = _norm_series(df["name"])
    return df.set_index("norm_name")[num_cols].to_dict("index")

def _load_gpu_bench_map(csv_path: Path) -> Dict[str, Dict[str, int]]:
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path)
    _ensure_cols(df, list(GPU_BENCH_COL_MAP.keys()))
    df = df[["name", *GPU_BENCH_COL_MAP]].rename(columns=GPU_BENCH_COL_MAP)
    num_cols = list(GPU_BENCH_COL_MAP.values())
    df[num_cols] = (
        df[num_cols]
          .replace("-", 0)
          .apply(pd.to_numeric, errors="coerce")
          .fillna(0)
          .astype(int)
    )
    return df.set_index("name")[num_cols].to_dict("index")

def _attach_cpu_benchmarks(products: List[Dict[str, Any]], bench_map: Mapping[str, Mapping[str, int]]) -> None:
    for prod in products:
        norm = _norm_series(pd.Series([prod.get("name", "")]))[0]
        if (scores := bench_map.get(norm)):
            prod.setdefault("spec", {}).update({k: str(v) for k, v in scores.items() if v})

def _attach_gpu_benchmarks(products: List[Dict[str, Any]], bench_map: Mapping[str, Mapping[str, int]]) -> None:
    for prod in products:
        spec     = prod.setdefault("spec", {})
        chipset  = spec.get("chipset", "").strip().lower()
        memcap   = spec.get("memory_capacity", "").strip()

        for bench_name, scores in bench_map.items():
            tokens = bench_name.replace("(", "").replace(")", "").split()
            if "GB" in bench_name:
                model, mem_tok = " ".join(tokens[:-1]).lower(), tokens[-1]
            else:
                model, mem_tok = bench_name.lower(), None
            if model == chipset and (mem_tok is None or mem_tok == memcap):
                spec.update({k: str(v) for k, v in scores.items() if v})
                break

# ─────────────────────────── storage consolidator ────────────────────────────
def _consolidate_storage(final_dir: Path) -> None:
    """SSD/HDD → category 필드 추가 후 Storage_parsed.json 으로 병합"""
    ssd_file = final_dir / "SSD_final.json"
    hdd_file = final_dir / "HDD_final.json"
    final_file = final_dir / "Storage_final.json"

    if not ssd_file.exists() and not hdd_file.exists():
        print("[!] SSD/HDD 파일이 없습니다 → 통합 스킵")
        return

    def _load_and_tag(path: Path, cat: str) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        data = _load_json(path)
        for prod in data:                           # spec 안에 category 삽입
            prod.setdefault("spec", {})["category"] = cat
        return data

    storage_products = (
        _load_and_tag(ssd_file, "SSD") +
        _load_and_tag(hdd_file, "HDD")
    )

    _save_json(storage_products, final_file)
    print(f"Storage → {final_file.relative_to(final_dir.parent.parent)} created")

    # ─── SSD/HDD 최종 JSON 삭제 ───────────────────────────
    for obsolete in (ssd_file, hdd_file):
        if obsolete.exists():
            obsolete.unlink()
            print(f"[-] {obsolete.name} removed (merged into Storage_final.json)")

# ───────────────────────────── main orchestrator ───────────────────────────────────── #
def enrich_products(root: Path = DEF_ROOT) -> None:
    parsed_dir = root / "data" / "parsed"
    raw_dir    = root / "data" / "raw"
    final_dir = root / "data" / "final"
    final_dir.mkdir(parents=True, exist_ok=True)

    # 벤치맵은 한 번만 로드
    cpu_bench_map = _load_cpu_bench_map(raw_dir / "CPU" / "CPU_benchmark.csv")
    gpu_bench_map = _load_gpu_bench_map(raw_dir / "VGA" / "GPU_benchmark.csv")

    for part in PARTS:
        parsed_json = parsed_dir / f"{part}_parsed.json"
        final_json = final_dir / f"{part}_final.json"

        if not parsed_json.exists():
            print(f"[!] {parsed_json.name} not found – skip")
            continue

        products = _load_json(parsed_json)

        # 가격·재고 업데이트
        price_csv = raw_dir / part / f"{part}_price.csv"
        _update_price_stock(products, _load_price_map(price_csv))

        # 벤치 점수 연결 (CPU, VGA만)
        if part == "CPU":
            _attach_cpu_benchmarks(products, cpu_bench_map)
        elif part == "VGA":
            _attach_gpu_benchmarks(products, gpu_bench_map)

        _save_json(products, final_json)
        print(f"{part} -> {final_json.relative_to(root)} updated")

    _consolidate_storage(final_dir)
# ───────────────────────────────────── CLI ─────────────────────────────────────────── #
if __name__ == "__main__":
    ap = argparse.ArgumentParser("Attach price/stock (all parts) and benchmark data (CPU/VGA)")
    ap.add_argument("--dir", type=Path, default=DEF_ROOT, help="Project root")
    enrich_products(ap.parse_args().dir)
