import sqlite3

PROJECT_NAME = "../askspec.db"

def create_tables():
    conn = sqlite3.connect(PROJECT_NAME)
    cursor = conn.cursor()
    # 외래키 활성화
    cursor.execute("PRAGMA foreign_keys = ON;")

    # 1) users
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        profile     TEXT,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2) sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL REFERENCES users(id),
        session_name  TEXT,
        created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3) messages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id        INTEGER NOT NULL REFERENCES sessions(id),
        role              TEXT    NOT NULL,
        content           TEXT,
        mode              TEXT    NOT NULL, 
        created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4) components
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS components (
        product_id  INTEGER PRIMARY KEY,
        category    TEXT    NOT NULL,
        name        TEXT    NOT NULL,
        spec        TEXT,  -- JSON stored as TEXT
        price       INTEGER,
        in_stock    BOOLEAN  NOT NULL,
        image_url   TEXT     NOT NULL,
        product_url TEXT     NOT NULL,
        updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 5) components_web
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS components_web (
        product_web_id  INTEGER PRIMARY KEY,
        category        TEXT    NOT NULL,
        name            TEXT    NOT NULL,
        spec            TEXT,  -- JSON stored as TEXT
        price           INTEGER,
        in_stock        BOOLEAN  NOT NULL,
        image_url       TEXT     NOT NULL,
        product_url     TEXT     NOT NULL,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 6) estimates
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS estimates (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL REFERENCES users(id),
        title             TEXT,
        score_json        TEXT,  -- JSON stored as TEXT
        total_price       INTEGER,
        compatibility     BOOLEAN,
        is_saved          BOOLEAN  DEFAULT FALSE,
        overall_reason    TEXT,
        created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 7) estimate_items
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS estimate_items (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        estimate_id          INTEGER NOT NULL REFERENCES estimates(id),
        product_id           INTEGER REFERENCES components(product_id),
        product_web_id       INTEGER REFERENCES components_web(product_web_id),
        quantity             INTEGER NOT NULL DEFAULT 1,
        selection_reason     TEXT,
        CHECK (
            (product_id IS NOT NULL AND product_web_id IS NULL)
            OR 
            (product_id IS NULL     AND product_web_id IS NOT NULL)
        )
    );
    """)

    # 8) score_statistics
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS score_statistics (
        name            TEXT PRIMARY KEY,
        category        TEXT NOT NULL,
        value           REAL NOT NULL,
        updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()

def drop_estimates():
    # 외래키 제약 해제 (필요하다면)
    with sqlite3.connect(PROJECT_NAME) as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        # estimates 테이블 드롭
        conn.execute("DROP TABLE IF EXISTS estimates;")
        # (옵션) 필요하다면 estimate_items 도 같이 드롭
        conn.execute("DROP TABLE IF EXISTS estimate_items;")
        # 외래키 다시 활성화
        conn.commit()  # <-- DDL 커밋
        conn.execute("PRAGMA foreign_keys = ON;")

if __name__ == "__main__":
    create_tables()
    print("✅ Tables created.")
