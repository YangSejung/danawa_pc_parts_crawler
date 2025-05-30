# 예시 파일. 수정해야 함
# import sqlite3
# from contextlib import contextmanager
#
# DB_PATH = "askspec.db"
#
# @contextmanager
# def get_connection():
#     conn = sqlite3.connect(DB_PATH)
#     conn.row_factory = sqlite3.Row
#     try:
#         yield conn
#         conn.commit()
#     finally:
#         conn.close()
#
# def insert_user(profile: dict):
#     with get_connection() as conn:
#         cursor = conn.cursor()
#         cursor.execute(
#             "INSERT INTO users (profile) VALUES (?)",
#             (json.dumps(profile),)
#         )
#         return cursor.lastrowid
#
# def fetch_user_by_id(user_id: int):
#     with get_connection() as conn:
#         cursor = conn.cursor()
#         cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
#         return cursor.fetchone()