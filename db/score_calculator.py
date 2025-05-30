"""
CPU/VGA 파이널 JSON을 순회하여
1) 각 벤치마크 최고점(max_xxx)
2) CPU·GPU 최대 가성비(max_cpu_value, max_gpu_value)
을 계산해 출력/DB에 저장한다.
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List

# ────────────────────── 경로 ──────────────────────
ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "data" / "final"
CPU_JSON = FINAL / "CPU_final.json"
GPU_JSON = FINAL / "VGA_final.json"
DB_PATH  = ROOT / "askspec.db"

# ──────────────── 메트릭 정의 & 매핑 ───────────────
CPU_METRICS = ["cinebench_r23_single",
               "cinebench_r23_multi",
               "blender_cpu",
               "geekbench6_single",
               "geekbench6_multi"]

GPU_METRICS = ["3d_mark",
               "geekbench6_opencl",
               "blender_gpu"]

# ─────────────────── 유틸 ─────────────────────────
def _load_json(path: Path) -> List[Dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def _max_by_metric(products: List[Dict], metrics: List[str]) -> Dict[str, int]:
    """리스트에서 각 metric 의 최댓값 반환"""
    maxima = {m: 0 for m in metrics}
    for p in products:
        spec = p.get("spec", {})
        for m in metrics:
            maxima[m] = max(maxima[m], int(float(spec.get(m, 0) or 0)))
    return maxima

# ─────────────────── 1) 최고점 계산 ─────────────────
cpu_products = _load_json(CPU_JSON)
gpu_products = _load_json(GPU_JSON)

cpu_max = _max_by_metric(cpu_products, CPU_METRICS)
gpu_max = _max_by_metric(gpu_products, GPU_METRICS)

# ───────────── 2) 공통 스코어 계산기 ───────────────
def _calc_score(spec: Dict[str, float],
                metrics: List[str],
                max_map: Dict[str, int]) -> float:
    """선택 지표만 사용해 0~100 점 환산"""
    total, used = 0.0, 0
    for m in metrics:
        vmax = max_map.get(m, 0)
        vcur = float(spec.get(m, 0) or 0)
        if vmax > 0 and vcur > 0:
            total += vcur / vmax
            used  += 1
    if used == 0:
        return 0.0
    return total / used * 100      # 100점 만점

# 래퍼 함수
cpu_score = lambda spec: _calc_score(spec, CPU_METRICS, cpu_max)
gpu_score = lambda spec: _calc_score(spec, GPU_METRICS, gpu_max)

max_cpu_value = 0.0
for p in cpu_products:
    price = p.get("price") or 0
    if price > 0:
        value = cpu_score(p.get("spec", {})) / price
        max_cpu_value = max(max_cpu_value, value)

max_gpu_value = 0.0
for p in gpu_products:
    price = p.get("price") or 0
    if price > 0:
        value = gpu_score(p.get("spec", {})) / price
        max_gpu_value = max(max_gpu_value, value)

# ─────────────── 3) DB 저장 (옵션) ────────────────

conn = sqlite3.connect(DB_PATH)
cur  = conn.cursor()

def upsert(name: str, category: str, value: float):
    cur.execute("""
        INSERT INTO max_benchmark_scores(name, category, max_value)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            category   = excluded.category,   -- ← 함께 갱신
            max_value  = excluded.max_value,
            updated_at = CURRENT_TIMESTAMP
    """, (name, category, value))

# 벤치 최고점
for k, v in cpu_max.items():
    upsert(k, "CPU", v)
for k, v in gpu_max.items():
    upsert(k, "GPU", v)

# 가성비 최고점
upsert("max_cpu_value", "CPU", max_cpu_value)
upsert("max_gpu_value", "GPU", max_gpu_value)

conn.commit()
conn.close()

print("=== Max Benchmarks ===")
print(cpu_max)
print(gpu_max)
print(f"max_cpu_value : {max_cpu_value:.8f}")
print(f"max_gpu_value : {max_gpu_value:.8f}")


