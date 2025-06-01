from dotenv import load_dotenv
import os, glob, json
from typing import Dict, List
from pathlib import Path
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI
# ------------- 환경 변수 ----------------
load_dotenv()
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
INDEX_NAME = "pc-components"
DIMENSION  = 1536
COMPATIBILITY_SPEC: dict[str, list[str]] = {
    "CPU": ["memory_type", "tdp", "ppt", "pbp-mtp", "pcie_versions","socket"],
    "Cooler": ["intel_sockets", "amd_sockets", "width", "depth", "height", "connector", "radiator_rows", "radiator_width", "radiator_thickness", "tdp", "tower_design"],
    "Motherboard": ["socket", "chipset", "vga_interface", "memory_max_capacity", "memory_type", "memory_slots", "pcle_versions", "pciex16_slots", "pciex8_slots", "pciex4_slots", "pciex1_slots", "m2_slots", "m2_connection", "sata3_slots", "form_factor", "memory_frequency", "power_phases"],
    "Memory": ["memory_type"],
    "VGA": ["power_ports", "length", "thickness", "pcie_interface", "psu_requirement", "power_consumption"],
    "Storage": ["form_factor", "pcie_interface","interface"],
    "Case": ["form_factor", "max_gpu_length", "max_cpu_cooler_height", "width", "depth", "height"],
    "PSU": ["depth", "main_power_connectors", "aux_power_connectors", "pcie_16pin_connectors", "pcie_8pin_connectors", "sata_connectors", "ide_4pin_connectors", "fdd_connectors", "form_factor", "rail_info", "rail_12v_availability", "wattage"],
}
PERFORMANCE_SPEC: dict[str, list[str]] = {
    "CPU": ["base_clock", "boost_clock", "l2_cache", "l3_cache", "cores", "threads", "max_memory_clock", "cinebench_r23_single", "cinebench_r23_multi", "geekbench6_single", "geekbench6_multi", "blender_cpu"],
    "Cooler": ["max_airflow", "static_pressure", "max_noise"],
    "Motherboard": ["memory_frequency", "power_phases"],
    "Memory": ["timings", "frequency", "total_memory_capacity"],
    "VGA": ["base_clock", "boost_clock", "stream_processors", "memory_capacity", "chipset", "memory_type", "3d_mark", "geekbench6_opencl", "blender_gpu", "average_fps_by_1080p_high", "average_fps_by_1080p_ultra", "average_fps_by_1440p_ultra", "average_fps_by_4k_high"],
    "Storage":["pcie_interface", "sequential_read", "sequential_write", "read_iops", "write_iops", "capacity", "category", "mtbf", "tbw", "nand_type", "has_dram", "dram","recording_method", "rpm", "buffer_size", "sequential_speed", "capacity"],
    "Case": [],
    "PSU": ["eta_certification", "lambda_certification", "efficiency"],
}

# ---------- 1) 클라이언트 초기화 ------------
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pc = Pinecone(api_key = PINECONE_API_KEY)

if not pc.has_index(INDEX_NAME):
    pc.create_index(
        name=INDEX_NAME,
        dimension=DIMENSION,
        metric="cosine",
        spec=ServerlessSpec(
            cloud='aws',
            region='us-east-1'
        )
    )
else:
    print(f"[Info] Index '{INDEX_NAME}' already exists, skip creation.")

index = pc.Index(INDEX_NAME)

# ------------ 유틸 함수 ----------------
def compatibility_spec(spec: Dict[str, str], category) -> str:
    parts = []
    for k, v in spec.items():
        if k not in COMPATIBILITY_SPEC.get(category):
            continue
        if isinstance(v, list):
            v = ", ".join(map(str, v))
        parts.append(f"{k}: {v}")
    return "; ".join(parts)

def performance_spec(spec: Dict[str, str], category) -> str:
    parts = []
    for k, v in spec.items():
        if k not in PERFORMANCE_SPEC.get(category):
            continue
        if isinstance(v, list):
            v = ", ".join(map(str, v))
        parts.append(f"{k}: {v}")
    return "; ".join(parts)

def spec_to_text(spec: Dict[str, str]) -> str:
    """dict → 'key value' 로 이어붙여 임베딩용 텍스트 생성"""
    parts = []
    for k, v in spec.items():
        if isinstance(v, list):
            v = ", ".join(map(str, v))
        parts.append(f"{k}: {v}")
    return "; ".join(parts)

def embed_texts(texts: List[str]) -> List[List[float]]:
    """배치 임베딩(OpenAI)"""
    resp = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [d.embedding for d in resp.data]

def build_meta(item: Dict, category: str) -> Dict:
    """가격·재고가 비어 있으면 필드 자체를 생략한다."""
    meta = {
        "product_id": item["id"],
        "name": item["name"],
        "product_url": item["product_url"],
        "image_url": item["image_url"],
        "category": category,
        "price": item["price"],
        "in_stock": item["in_stock"],
        "performance_spec": performance_spec(item['spec'], category),
        "compatibility_spec": compatibility_spec(item['spec'], category),
        "text": spec_to_text(item['spec'])
    }
    return meta

# ------------------ json 파일 로드 및 변환 -------------
if __name__ == "__main__":
    # 파일 경로
    ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = ROOT / "data" / "final"
    json_files = glob.glob(str(DATA_DIR / "*_final.json"))

    records = []
    for fp in json_files:
        category = Path(fp).stem.replace("_final", "")  # CPU, VGA …
        with open(fp, encoding="utf-8") as f:
            for item in json.load(f):
                if item.get('price') is None:
                    item['price'] = "가격 정보 없음"
                vector_id = str(item['id'])      # 유니크 ID
                text      = f"{item['name']}; price {item['price']}; {spec_to_text(item['spec'])}"
                metadata = build_meta(item, category)
                records.append((vector_id, text, metadata))

    # ------------------ 배치 임베딩 & 업서트 ----------------
    BATCH = 100
    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        ids, texts, metas = zip(*batch)
        vectors = embed_texts(list(texts))
        index.upsert(vectors=list(zip(ids, vectors, metas)))
        print(f"[{i+len(batch):>5}/{len(records)}] upsert 완료")
