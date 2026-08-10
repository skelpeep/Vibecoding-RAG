# atguigu/import_process/nodes/node_item_name_recognition.py
import json

from langchain.chat_models import init_chat_model
from pymilvus import DataType

from atguigu.config.config import LLMConfig, MilvusConfig
from atguigu.config.prompt import ITEM_NAME_SYSTEM_PROMPT, ITEM_NAME_USER_PROMPT_TEMPLATE
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import get_milvus_client


class NodeItemNameRecognition(NodeBase):
    """
    主体识别节点：主体识别与标签提取
    """

    name = "node_item_name_recognition"

    def get_chunks(self, state):
        chunks = state.get("chunks")
        file_title = state.get("file_title")
        if not chunks:
            logger.error(f"chunks是空的，必须有值才能进行主体识别")
            raise Exception("chunks是空的，必须有值才能进行主体识别")
        if not file_title:
            logger.error(f"file_title是空的，必须有值才能进行主体识别")
            raise Exception("file_title是空的，必须有值才能进行主体识别")
        return chunks, file_title

    def get_chunks_content(self, chunks, file_title):
        # 根据chunks去让大模型识别主体名称（商品名字）
        # chunks有点多，内容加起来可能超过大模型的token限制，所以我们是从chunks当中截取k个
        chunk_k_list = chunks[:10]
        max_len = 10000
        content_str = "\n"
        # 需要把这些chunk的title content file_title part把这些需要的数据拼接成一个字符串，还得把这个字符串合并拼接到一个大的字符串
        for idx, chunk in enumerate(chunk_k_list, start=1):
            title = chunk.get("title")
            content = chunk.get("content")
            chunk_str = f"[切片{idx}]\n{file_title}\n{title}\n{content}\n"
            # 判断content_str是不是已经超过max_len
            if len(content_str) > max_len:
                logger.info(f"已经超过最大长度，不再拼接")
                break
            content_str += chunk_str
        content_str = content_str[:max_len]
        return content_str

    def get_item_name(self, content_str, file_title):
        # 准备大模型去识别得到主体名称
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature,
        )
        messages = [
            {"role": "system", "content": ITEM_NAME_SYSTEM_PROMPT},
            {"role": "user",
             "content": ITEM_NAME_USER_PROMPT_TEMPLATE.format(file_title=file_title, context=content_str)},
        ]
        res = llm.invoke(input=messages)
        item_name = res.content
        item_name = item_name.replace(" ", "").replace("\n", "").replace("\t", "")
        if not item_name:
            # itemname可能没有识别到，用文件名代替，但是文件名也可能是没有意义的，此时后期我们chunk当中file_title和item_name
            # 就都没有意义了，但是我们还是得给这个chunk机会，我们后期再存储chunk的时候，向量化的内容是item_name拼接content内容
            # 此时这个向量就可能被获取检索检索到。假设这种chunk后期检索相似度很低，那么大不了不要这个chunk
            item_name = file_title
        return item_name

    def create_milvus_collection(self):
        # 把item_name要向量化保存milvus(原因在于后期检索的时候需要,)
        # 检索的时候第一个节点就是做用户意图识别，用户问问题，问的是和哪个商品相关的问题，我们需要去识别一下（历史消息）
        # 识别出来的意图是哪个商品，需要在存储的商品主体milvus当中去做一个对比（相似性查找）
        # 识别出来的意图产品如果找到了对应的item_name，那么我们就知道用户问的这个问题是和哪个商品相关的问题
        milvus_client = get_milvus_client()
        if not milvus_client:
            logger.error("初始化milvus_client失败")
            raise Exception("初始化milvus_client失败")
        # 幂等性删除一般不会对整张表进行操作，一般都是针对表里面的相同数据进行幂等删除
        collection_name = MilvusConfig.item_name_collection
        if not milvus_client.has_collection(collection_name):
            schema = milvus_client.create_schema(
                auto_id=True,
            )

            schema.add_field(
                field_name="id",
                datatype=DataType.INT64,
                is_primary=True,
            ).add_field(
                field_name="item_name",
                datatype=DataType.VARCHAR,
                max_length=100,
            ).add_field(
                field_name="file_title",
                datatype=DataType.VARCHAR,
                max_length=100,
            ).add_field(
                field_name="dense_vector",
                datatype=DataType.FLOAT_VECTOR,
                dim=1024
            ).add_field(
                field_name="sparse_vector",
                datatype=DataType.SPARSE_FLOAT_VECTOR,
            )

            index_params = milvus_client.prepare_index_params()
            index_params.add_index(
                field_name="dense_vector",
                index_type="IVF_FLAT",  # 暴力检索
                metric_type="COSINE",
                params={"nlist": 128, "nprobe": 10},  # 提升效率否则暴力检索虽然准备效率太低
            )

            index_params.add_index(
                field_name="sparse_vector",
                index_type="SPARSE_INVERTED_INDEX",  # 暴力检索
                metric_type="IP",
                params={
                    "inverted_index_algo": "DAAT_MAXSCORE",
                    # 高效的稀疏检索算法
                    "normalize": True,
                    # ↑ L2 归一化，让内积 (IP) 等价于余弦相似度
                    "quantization": "none"
                    # ↑ 关闭量化，保持原始精度：模型生成的向量已经压缩的一半的精度了（BGE_FP16=1），这里就不再压缩了
                    # "quantization": "none" → 存储原始向量，不压缩
                    # "quantization": "sq8" → 存储压缩后的向量（8-bit 量化
                }
            )

            milvus_client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )
        return collection_name, milvus_client

    def insert_data_backup(self, chunks, collection_name, file_title, item_name, milvus_client):
        # 准备数据进行插入数据
        # 幂等删除item_name相同的数据
        # milvus要删除数据，需要先去加载一下这个表
        # 这里在删除表当中的同名数据，不是字段也不是表
        milvus_client.load_collection(collection_name=collection_name)
        safe_item_name = item_name.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
        filter_str = f"item_name == '{safe_item_name}'"
        milvus_client.delete(collection_name=collection_name, filter=filter_str)
        # 插入数据
        # 通过bgem3去向量化
        embedding = get_bge_m3_embedding([item_name])
        data = {
            "item_name": item_name,
            "file_title": file_title,
            "dense_vector": embedding.get("dense")[0],
            "sparse_vector": embedding.get("sparse")[0],
        }
        result = milvus_client.insert(
            collection_name=collection_name,
            data=data
        )
        # 回填item_name到每个chunk
        for chunk in chunks:
            chunk["item_name"] = item_name


    def process(self, state: ImportGraphState):
        #第一大步：获取上一个节点返回的chunks(切片)和file_title(文件名)
        chunks, file_title = self.get_chunks(state)

        #第二大步：根据chunks去切10个，把内容整理成一个字符串
        content_str = self.get_chunks_content(chunks, file_title)

        #第三大步：准备大模型根据上一步得到的字符串去识别得到主体名称
        item_name = self.get_item_name(content_str, file_title)

        #第四大步：创建collection如果还没有的话
        collection_name, milvus_client = self.create_milvus_collection()

        #第五大步：插入数据到milvus当中，顺便把item_name回填到每个chunk
        self.insert_data_backup(chunks, collection_name, file_title, item_name, milvus_client)

        with open(r"D:\output\hak180产品安全手册\item_name_chunks.json","w",encoding="utf-8") as f:
            # json.dump(chunks, f, ensure_ascii=False, indent=4)
            f.write(json_format(chunks))

        return {
            "item_name": item_name,
            "chunks": chunks
        }



if __name__ == '__main__':
    node = NodeItemNameRecognition()
    # with open(r"D:\output\hak180产品安全手册\chunks.json","r",encoding="utf-8") as f:
    #     chunks_json = f.read()  如果这样写，下面需要反序列化
    with open(r"D:\output\hak180产品安全手册\chunks.json","r",encoding="utf-8") as f:
        chunks= json.load(f)

    init_state = {
        "chunks":chunks,
        "file_title":"hak180产品安全手册"
    }
    result = node(init_state)
    logger.info(json_format(result))