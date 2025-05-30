from dotenv import load_dotenv
import os
from pinecone import Pinecone
from openai import OpenAI
# ------------- 환경 변수 ----------------
load_dotenv()
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
INDEX_NAME = "pc-components"
DIMENSION  = 1536

# ---------- 1) 클라이언트 초기화 ------------
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pinecone = Pinecone(api_key = PINECONE_API_KEY)

index = pinecone.Index(INDEX_NAME)

# 3) 쿼리 텍스트를 임베딩하는 함수
def embed_query(text: str) -> list[float]:
    resp = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    # 첫 번째 결과의 embedding 벡터 반환
    # return resp["data"][0]["embedding"]
    return [d.embedding for d in resp.data]

# 4) Pinecone에서 유사도 검색 수행
def search_pinecone(query: str, top_k: int = 10):
    # 4.1) 쿼리를 임베딩
    vector = embed_query(query)
    # 4.2) 인덱스에 질의
    result = index.query(
        vector=vector,
        top_k=top_k,
        include_metadata=True  # 메타데이터(예: name, specs) 함께 가져오기
    )
    return result

# 5) 결과 출력
if __name__ == "__main__":
    query_text = "인텔 코어i5-14세대 14400F"
    result = search_pinecone(query_text, top_k=10)

    print(f"쿼리: {query_text}\n상위 {len(result['matches'])}개 결과:")
    for i, match in enumerate(result["matches"], start=1):
        metadata = match.get("metadata", {})
        print(f"{i}. id={match['id']}, score={match['score']:.4f}")
        # 예시로 name과 price를 메타데이터에서 출력
        print(f"   - name : {metadata.get('name', 'N/A')}")
        print(f"   - price: {metadata.get('price', 'N/A')}")
        print(f"   - category: {metadata.get('category', 'N/A')}")
        print(f"   - in_stock: {metadata.get('in_stock', 'N/A')}")
        print(f"   - image_url: {metadata.get('image_url', 'N/A')}")
        print(f"   - product_url: {metadata.get('product_url', 'N/A')}")
        print(f"   - product_id: {metadata.get('product_id', 'N/A')}")
