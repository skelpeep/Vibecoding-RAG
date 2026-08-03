# atguigu/import_process/nodes/node_md_img.py
import os
import re
from pathlib import Path

from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger


class NodeMDImg(NodeBase):
    """
    MarkDown图片处理节点：多模态图片理解
    """

    name = "node_md_img"

    def process(self, state: ImportGraphState):

        # 1、获取文件内容和图片名字列表
        md_path = state.get("md_path",'')
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

        # 构造图片的存储路径
        images_dir_path_obj = md_path_obj.parent / "images"
        if not images_dir_path_obj.exists():
            return md_content

        # 判断图片目录当中有没有货
        image_name_list = os.listdir(images_dir_path_obj)# 列出目录下的所有文件和文件夹的名字
        if not image_name_list:
            logger.info("图片目录为空")
            return md_content

        # 拿到内容和本地图片的名字列表

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
            start,end = match.span()
            pre_text = md_content[max(0,start-MAX_CONTEXT_LENGTH):start]
            post_text = md_content[end:min(len(md_content),end+MAX_CONTEXT_LENGTH)]

            # 把图片和上下文构造成字典，添加到准备好的列表当中
            # 构造这个图片的路径一起放到字典
            image_path = str(images_dir_path_obj / image_name)

            image_with_context_list.append({
                "image_name": image_name,
                "pre_text": pre_text,
                "post_text": post_text,
                "image_path":image_path
            })

        print(json_format(image_with_context_list))



        return state

if __name__ == '__main__':
    node = NodeMDImg()
    init_state = {
        "md_path":r"D:\output\hak180产品安全手册\hak180产品安全手册.md"
    }
    result = node(init_state)
    logger.info(json_format(result))



