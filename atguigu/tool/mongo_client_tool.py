# import pymongo
# myclient = pymongo.MongoClient("mongodb://localhost:27017/")
# mydb = myclient["runoobdb"]
# mycol = mydb["sites"]
import time

from pymongo import MongoClient

from atguigu.config.config import MongoConfig

mongo_client = None
def get_mongo_client():
    global mongo_client
    if not mongo_client:
        mongo_client = MongoClient(MongoConfig.mongo_url)
    return mongo_client

collection = None
db = None
def get_mongo_collection():
    global collection
    global db
    mongo_client = get_mongo_client()
    if db is None:
        db = mongo_client[MongoConfig.mongo_db_name]
    if collection is None:
        collection = db["chat_history"]
        collection.create_index([("_id", 1),("ts",-1),("session_id",1)])
    return collection


# 创建对历史记录增删改查的方法
# 1、获取最近的多少条历史记录 limit来限定  方法目的是后期再意图识别的时候需要获取历史记录来识别
def get_recent_history_list(session_id,limit=10):
    collection = get_mongo_collection()
    result = collection.find({"session_id": session_id}).sort("ts", -1).limit(limit)
    return list(result)  #我们拿到的不是列表，而是游标对象，需要自己强装



def add_or_update_history(session_id,role,text,rewritten_query=None,item_names=None,image_urls=None,ts=None,_id=None):
    # 全量更新和增量更新
    # 为什么人们在封装数据库增和改的时候全部合二为一写一个方法或者函数，就是因为他们传递参数的时候唯一不同就是id
    # 如果是修改，那么id一定存在
    # 如果是新增，那么id一定不存在
    collection = get_mongo_collection()
    if _id:
        # 修改操作
        data = {
            "_id": _id,
            "session_id": session_id,
            "role": role,
            "text": text,
            "rewritten_query": rewritten_query,
            "item_names": item_names,
            "image_urls": image_urls,
            "ts": ts or time.time(),
        }
        collection.update_one({"_id": _id}, {"$set": data})
        return _id
    else:
        # 新增操作
        data = {
            "session_id": session_id,
            "role": role,
            "text": text,
            "rewritten_query": rewritten_query,
            "item_names": item_names,
            "image_urls": image_urls,
            "ts": ts or time.time(),
        }
        result = collection.insert_one(data)
        print(result.inserted_id)
        return result.inserted_id


def clear_history(session_id):
    collection = get_mongo_collection()
    collection.delete_many({"session_id": session_id})


def update_item_names_and_query(ids,item_names=None,rewritten_query=None):
    collection = get_mongo_collection()
    data = {
        "item_names": item_names,
        "rewritten_query": rewritten_query,
    }
    collection.update_many({"_id": {"$in":ids}},{"$set":data})

if __name__ == '__main__':
    # add_or_update_history("test_001", "user", "咨询下烫金机。")
    # add_or_update_history("test_001", "assistant", "您好。请问是哪个型号")
    # result = add_or_update_history("test_001", "user", "hak180")
    # print(result,type(result))
    # add_or_update_history("test_001", "assistant", "具体有什么问题呢？")


    # result = get_recent_history_list("test_001")
    # print(result)

    clear_history("test_001")






