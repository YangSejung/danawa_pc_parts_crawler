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
        # "product_id": item["id"],
        "name": item["name"],
        "product_url": item["product_url"],
        "image_url": item["image_url"],
        "category": category,
        "price": item["price"],
        "in_stock": item["in_stock"],
        "text": spec_to_text(item['spec'])
    }
    return meta

# ------------------ json 파일 로드 및 변환 -------------
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
                continue

            vector_id = str(item['id'])      # 유니크 ID
            text      = f"{item['name']}; price {item['price']}; {spec_to_text(item['spec'])}"
            metadata = build_meta(item, category)
            records.append((vector_id, text, metadata))

# print(len(records))
# for ids, texts, metas in records[:5]:
#     print(metas)
#     print(texts)

# ------------------ 배치 임베딩 & 업서트 ----------------
# BATCH = 100
# for i in range(0, len(records), BATCH):
#     batch = records[i : i + BATCH]
#     ids, texts, metas = zip(*batch)
#     vectors = embed_texts(list(texts))
#     index.upsert(vectors=list(zip(ids, vectors, metas)))
#     # namespace="v2-2025-05-24"
#     print(f"[{i+len(batch):>5}/{len(records)}] upsert 완료")


# ---------------------- 테스트 --------------------------
# test
# qvec = embed_texts(["Motherboard"])[0]
# res = index.query(vector=qvec, top_k=3, include_metadata=True)
# for match in res.matches:
#     print(match.id, match.score, match.metadata)