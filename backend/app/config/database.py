import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017/ai_client_outreach")
DB_NAME = "ai_client_outreach"
if "/" in MONGODB_URI.split("://")[-1]:
    path_part = MONGODB_URI.split("://")[-1].split("/")[-1].split("?")[0]
    if path_part:
        DB_NAME = path_part

client: AsyncIOMotorClient = None
db = None

async def connect_db():
    global client, db
    try:
        client = AsyncIOMotorClient(MONGODB_URI)
        db = client[DB_NAME]
        # Quick ping to verify connectivity
        await client.admin.command('ping')
        print(f"MongoDB connected to {DB_NAME}")
        return db
    except Exception as e:
        print(f"MongoDB connection warning/error: {e}")
        # Return db object anyway in case Mongo starts up shortly
        if client:
            db = client[DB_NAME]
        return db

async def close_db():
    global client
    if client:
        client.close()

def get_db():
    global db
    if db is None and client:
        return client[DB_NAME]
    return db

get_database = get_db

# Backend selection helpers (defaults to MongoDB unless DATABASE_BACKEND=firestore is set)
from app.config.firestore_config import (
    get_database_backend,
    is_firestore_backend,
    is_mongodb_backend,
)

