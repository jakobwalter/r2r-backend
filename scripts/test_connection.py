# test_db.py
from r2r_backend.db.base import engine
from r2r_backend.db.models import Base
from sqlalchemy import text


try:
    # Test connection
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("✅ Database connected!")

    # Check tables
    print("\nTables created:")
    for table in Base.metadata.tables.keys():
        print(f"  - {table}")

except Exception as e:
    print(f"❌ Error: {e}")