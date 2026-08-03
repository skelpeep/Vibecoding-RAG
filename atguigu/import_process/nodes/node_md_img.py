# atguigu/import_process/nodes/node_md_img.py
import base64
import os
import re
import time
from collections import deque
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI

from atguigu.config.config import LLMConfig
from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"


    def get_md_content(self,state):
        # 1、获取文件内容和图片名字列表
        md_path = state.get("md_path", '')
        if not md_path:
            logger.error("md_path必须提供")
            raise ValueError("md_path必须提供")

        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error("md文件不存在")
            raise FileNotFoundError(f"md文件{md_path}不存在")

        with open(md_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()

        if not md_content:
            logger.error("md文件内容为空")
            raise ValueError(f"md文件{md_path}内容为空")

        return md_content,md_path_obj

    def get_image_with_context_list(self,md_content,image_name_list,images_dir_path_obj):
        # 2、遍历图片名字，获取图片的上下文
        IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        MAX_CONTEXT_LENGTH = 250
        image_with_context_list = []
        for image_name in image_name_list:
            if Path(image_name).suffix.lower() not in IMAGE_EXTENSIONS:
                logger.warning(f"图片{image_name}不是支持的格式")
                continue
            # 构建图片在markdown当中的正则对象
            pattern = re.compile(r"!\[.*?\]\(.*?" + re.escape(image_name) + r"\)")
            match = pattern.search(md_content)
            print(match)
            if not match:
                logger.warning(f"图片{image_name}未被引用")
                continue

            # 获取匹配到的图片的起始和结束位置
            start, end = match.span()
            pre_text = md_content[max(0, start - MAX_CONTEXT_LENGTH):start]
            post_text = md_content[end:min(len(md_content), end + MAX_CONTEXT_LENGTH)]

            # 把图片和上下文构造成字典，添加到准备好的列表当中
            # 构造这个图片的路径一起放到字典
            image_path = str(images_dir_path_obj / image_name)

            image_with_context_list.append({
                "image_name": image_name,
                "pre_text": pre_text,
                "post_text": post_text,
                "image_path": image_path
            })
        return image_with_context_list

    def get_image_with_summary_list(self,image_with_context_list):
        #       根据上面的图片列表，进行大模型调用真正生成摘要
        dq = deque(maxlen=30)
        current_time = time.time()

        llm = init_chat_model(
            model=LLMConfig.llm_default_model,
            model_provider="openai",
            base_url=LLMConfig.openai_api_base,
            api_key=LLMConfig.openai_api_key,
            temperature=LLMConfig.llm_default_temperature,
        )


        image_with_summary_list = []
        for image_with_context in image_with_context_list:
            # 一进来，先去盲清一波过期的请求
            while dq and current_time - dq[0] > 60:
                dq.popleft()

            # 有两种情况，一种是有过期的被清理了有位置，一种是一上来就没有过期的还是满员
            # 判断是不是位置满了，如果满了就需要去等待，如果没有满我们就直接发请求把时间加入
            if dq and len(dq) == dq.maxlen:
                # 代表满员没位置，计算需要等待的时间
                need_wait_time = 60 - (current_time - dq[0])
                if need_wait_time > 0:
                    time.sleep(need_wait_time)  # 真正的等待
                    current_time = time.time()
                    while dq and current_time - dq[0] > 60:
                        dq.popleft()

            dq.append(current_time)

            #           先把图片内容base64编码
            with open(image_with_context.get("image_path"), 'rb') as f:
                image_data = f.read()
                base64_str = base64.b64encode(image_data).decode('utf-8')

            #           给大模型发请求
            #           构造提示词：我们参考阿里云百联给的视觉模型提示

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                # 这个格式就是base64在使用的时候的规定
                                "url": "data:image/jpeg;base64," + base64_str,
                            },
                        },
                        {"type": "text", "text": f"""
                                        这是一张图片，图片上文部分为"{image_with_context.get("pre_text")}"，
                                        下文部分为"{image_with_context.get("post_text")}"，
                                        请用中文简要总结这张图片的摘要,字数在50字以内。"""
                         },
                    ],
                },
            ]

            res = llm.invoke(messages)
            image_with_summary_list.append({
                "image_name": image_with_context.get("image_name"),
                "image_path": image_with_context.get("image_path"),
                "summary": res.content,
            })
        return image_with_summary_list

    def process(self, state: ImportGraphState):
        # 第一大步：获取md的内容和路径对象
        md_content,md_path_obj = self.get_md_content(state)
        # 构造图片的存储路径
        images_dir_path_obj = md_path_obj.parent / "images"
        if not images_dir_path_obj.exists():
            return {
                "md_content": md_content,
            }

        # 判断图片目录当中有没有货
        image_name_list = os.listdir(images_dir_path_obj)  # 列出目录下的所有文件和文件夹的名字
        if not image_name_list:
            logger.info("图片目录为空")
            return {
                "md_content": md_content,
            }

        # 第二大步：获取图片的上下文列表，根据图片正则拿到图片位置，获取上下文
        image_with_context_list = self.get_image_with_context_list(md_content,image_name_list,images_dir_path_obj)

        # 第三大步：根据第二步得到的上下文图片列表，进行大模型调用真正生成摘要，形成新的图片字典列表
        image_with_summary_list = self.get_image_with_summary_list(image_with_context_list)

        return image_with_summary_list


if __name__ == '__main__':
    node = NodeMDImg()
    init_state = {
        "md_path":r"D:\output\hak180产品安全手册\hak180产品安全手册.md"
    }
    result = node(init_state)
    logger.info(json_format(result))



