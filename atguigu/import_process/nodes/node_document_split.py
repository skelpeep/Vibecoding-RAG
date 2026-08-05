# atguigu/import_process/nodes/node_document_split.py
import re
from pathlib import Path

from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger


class NodeDocumentSplit(NodeBase):
    """
    文档切分节点：智能文档切片
    """

    name = "node_document_split"

    def process(self, state: ImportGraphState):
        md_path = state.get("md_path",'')
        if not md_path:
            logger.error("md_path必须提供")
            raise Exception("md_path必须提供")
        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error(f"文件不存在：{md_path}")
            raise Exception("文件不存在")

        file_title = state.get("file_title",'')
        if not file_title:
            file_title = md_path_obj.stem

        with open(md_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()

        if not md_content:
            logger.error(f"文件内容为空：{md_path}")
            raise Exception("文件内容为空")

        #统一换行符
        md_content = md_content.replace('\r\n', '\n').replace('\r', '\n')

        #按行切分
        md_line_list = md_content.split('\n')
        # 按照标题去合并行，所以我们就得遍历这个列表找标题

        # 写代码块的正则
        code_pattern = r"^(`{3,}|~{3,})"
        # 定义是否在代码块内的标志
        is_in_block = False #为了区分第几次碰到```和~~~
        marker = None  #记录代码块的起始字符串（```|~~~）
        title_pattern = r'^\s*#{1,6}\s+.+'
        current_index = 0  #切片从哪开始的下标

        section_list = []
        for idx,line in enumerate(md_line_list):
            line = line.strip()
            #判断行是不是标题,得先判断是不是在代码块内
            match = re.match(code_pattern, line)
            if match:
                if not is_in_block:
                    is_in_block = True
                    marker = match.group(1)
                    logger.info(f"开始代码块：{marker}")
                else:
                    if marker == match.group(1):
                        is_in_block = False
                        marker = None
                        logger.info(f"结束代码块")

            # 不在代码块，然后就可以判断是不是标题了
            if not is_in_block and re.match(title_pattern, line):
        #         不在代码块，也符合标题正则
                temp_list = md_line_list[current_index:idx]
                content = '\n'.join(temp_list)
                section_dict = {
                    "title":temp_list[0] if content.startswith('#') else "无标题",
                    "content":content,
                    "file_title":file_title
                }
                section_list.append(section_dict)
        #       更新起始切片位置
                current_index = idx

        # 最后一个切片,我们循环当中切片是把最后一个标题及内容漏掉的
        section_list.append({
            "title": md_line_list[current_index],
            "content": '\n'.join(md_line_list[current_index:]),
            "file_title": file_title
        })

        logger.info(json_format(section_list))








































        return state


if __name__ == '__main__':
    node = NodeDocumentSplit()
    init_state = {
        "md_path":r"D:\output\hak180产品安全手册\hak180产品安全手册_new.md",
        "file_title":"hak180产品安全手册"
    }
    result = node(init_state)
    logger.info(json_format(result))