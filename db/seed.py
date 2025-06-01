#!/usr/bin/env python3
import sqlite3
import json
import os

DB_PATH = "../askspec.db"

# 스크립트 위치 기준으로 data/parsed 디렉터리를 가리키도록 설정
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
FINAL_DIR = os.path.join(BASE_DIR, "data", "final")

def seed_components():
    """
    data/parsed 폴더의 각 *_parsed.json 파일을 읽고,
    components 테이블(product_id, category, name, spec_json,
    price, in_stock, image_url, product_url)에 INSERT/REPLACE 합니다.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    for filename in os.listdir(FINAL_DIR):
        if not filename.endswith("_final.json"):
            continue

        # 예: "CPU_parsed.json" → category="cpu"
        category = filename.split("_", 1)[0].lower()
        file_path = os.path.join(FINAL_DIR, filename)
        print(file_path)
        with open(file_path, encoding="utf-8") as f:
            products = json.load(f)

        for prod in products:
            cursor.execute("""
                INSERT OR REPLACE INTO components
                  (product_id, category, name,
                   spec, price, in_stock,
                   image_url, product_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prod["id"],
                category,
                prod["name"],
                json.dumps(prod.get("spec", {}), ensure_ascii=False),
                prod.get("price"),
                1 if prod.get("in_stock") else 0,
                prod.get("image_url"),
                prod.get("product_url")
            ))


    conn.commit()
    conn.close()
    print("Components 테이블에 시딩을 완료했습니다.")

if __name__ == "__main__":
    seed_components()
