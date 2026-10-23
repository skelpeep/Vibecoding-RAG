"""Owned stage-five turns. The historical unauthenticated collection is untouched."""
from functools import lru_cache

from pymongo import ASCENDING, MongoClient
from pymongo.write_concern import WriteConcern

from atguigu.config.config import MongoConfig, RuntimeConfig

COLLECTION_NAME = "kb_platform_chat_turns_v1"


class MongoHistory:
    def __init__(self):
        timeout = max(1000, int(RuntimeConfig.service_timeout * 1000))
        self.client = MongoClient(MongoConfig.mongo_url, serverSelectionTimeoutMS=timeout,
                                  connectTimeoutMS=timeout, socketTimeoutMS=timeout,
                                  timeoutMS=timeout, maxPoolSize=16)
        self.collection = self.client[MongoConfig.mongo_db_name].get_collection(
            COLLECTION_NAME, write_concern=WriteConcern(w="majority", wtimeout=timeout))

    def prepare(self):
        self.client.admin.command("ping")
        self.collection.create_index([("owner_id", ASCENDING), ("session_id", ASCENDING),
                                      ("created_at", ASCENDING)], name="owned_session_history")

    def create(self, turn):
        self.collection.insert_one(turn)

    def finish(self, owner_id, session_id, request_id, values):
        result = self.collection.update_one({"_id": request_id, "owner_id": owner_id,
                                             "session_id": session_id}, {"$set": values})
        if result.matched_count != 1:
            raise RuntimeError("Owned history placeholder missing")

    def list(self, owner_id, session_id, limit=100):
        cursor = self.collection.find({"owner_id": owner_id, "session_id": session_id}).sort(
            "created_at", -1).limit(limit)
        return list(reversed(list(cursor)))

    def delete(self, owner_id, session_id):
        self.collection.delete_many({"owner_id": owner_id, "session_id": session_id})

    def get(self, owner_id, session_id, request_id):
        return self.collection.find_one({"_id": request_id, "owner_id": owner_id, "session_id": session_id})


@lru_cache
def get_history_store():
    return MongoHistory()
