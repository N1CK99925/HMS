# app/migrations/mongo_indexes.py
# Creates all MongoDB indexes defined across all models.
# Run this ONCE after setting up a fresh MongoDB instance.
# Safe to run again — MongoDB skips indexes that already exist.
#
# Run with: python -m app.migrations.mongo_indexes

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

# Import index definitions from every model
from app.models.mongo.tenant import TENANT_INDEXES, COLLECTION_NAME as TENANT_COL
from app.models.mongo.patient import PATIENT_INDEXES, COLLECTION_NAME as PATIENT_COL
from app.models.mongo.staff import STAFF_INDEXES, COLLECTION_NAME as STAFF_COL
from app.models.mongo.department import DEPARTMENT_INDEXES, COLLECTION_NAME as DEPT_COL


async def create_indexes():
    client = AsyncIOMotorClient(settings.MONGO_URL)
    db = client[settings.MONGO_DB_NAME]

    index_map = {
        TENANT_COL:  TENANT_INDEXES,
        PATIENT_COL: PATIENT_INDEXES,
        STAFF_COL:   STAFF_INDEXES,
        DEPT_COL:    DEPARTMENT_INDEXES,
    }

    for collection_name, indexes in index_map.items():
        collection = db[collection_name]
        for idx in indexes:
            # create_index is idempotent — safe to call if index already exists
            await collection.create_index(
                idx["key"],
                unique=idx.get("unique", False),
                name=idx["name"],
                background=True,   # Don't lock the collection while building
            )
            print(f"  {collection_name}: index '{idx['name']}' ready")

    print("\nAll MongoDB indexes created.")
    client.close()


if __name__ == "__main__":
    asyncio.run(create_indexes())