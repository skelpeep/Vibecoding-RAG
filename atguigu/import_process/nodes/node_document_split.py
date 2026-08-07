# atguigu/import_process/nodes/node_document_split.py
import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter

from atguigu.import_process.base import NodeBase
from atguigu.import_process.state import ImportGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger


class NodeDocumentSplit(NodeBase):
    """
    文档切分节点：智能文档切片
    """

    name = "node_document_split"


    def get_md_content(self,state):
        md_path = state.get("md_path", '')
        if not md_path:
            logger.error("md_path必须提供")
            raise Exception("md_path必须提供")
        md_path_obj = Path(md_path)
        if not md_path_obj.exists():
            logger.error(f"文件不存在：{md_path}")
            raise Exception("文件不存在")

        file_title = state.get("file_title", '')
        if not file_title:
            file_title = md_path_obj.stem

        with open(md_path_obj, 'r', encoding='utf-8') as f:
            md_content = f.read()

        if not md_content:
            logger.error(f"文件内容为空：{md_path}")
            raise Exception("文件内容为空")

        # 统一换行符
        md_content = md_content.replace('\r\n', '\n').replace('\r', '\n')
        return md_content, file_title,md_path_obj

    def get_section_list(self,md_content,file_title):
        # 按行切分
        md_line_list = md_content.split('\n')
        # 按照标题去合并行，所以我们就得遍历这个列表找标题

        # 写代码块的正则
        code_pattern = r"^(`{3,}|~{3,})"
        # 定义是否在代码块内的标志
        is_in_block = False  # 为了区分第几次碰到```和~~~
        marker = None  # 记录代码块的起始字符串（```|~~~）
        title_pattern = r'^\s*#{1,6}\s+.+'
        current_index = 0  # 切片从哪开始的下标
        section_list = []
        for idx, line in enumerate(md_line_list):
            line = line.strip()
            # 判断行是不是标题,得先判断是不是在代码块内
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
                    "title": temp_list[0] if content.startswith('#') else "无标题",
                    "content": content,
                    "file_title": file_title
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

        return section_list

    def get_final_section_list(self,section_list,md_path_obj,file_title):
        # 长切短合
        max_length = 300
        over_lap = 30
        final_section_list = []

        spliter = RecursiveCharacterTextSplitter(
            separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " "],
            chunk_size=max_length,
            chunk_overlap=over_lap
        )

        for section in section_list:
            title = section.get("title")
            content = section.get("content")
            #     求真实的内容 = content - 标题
            #     目的是为了把标题去除，切分只切分真正的内容，切完之后，每个chunk都需要在前面加上标题
            real_content = content[len(title):] if content.startswith('#') else content

            if len(real_content) < max_length:
                final_section_list.append({
                    **section,
                    "part": 0
                })
                continue
            # 如果内容当中包含表格，防止表格被切断，干脆就不切了
            if "<table" in real_content:
                final_section_list.append({
                    **section,
                    "part": 0
                })
                continue

            #     真正的切分
            splite_chunk_list = spliter.split_text(real_content)
            for idx, splite_chunk in enumerate(splite_chunk_list, start=1):
                final_section_list.append({
                    "title": title,
                    "file_title": file_title,
                    "content": title + "\n\n" + splite_chunk,
                    "part": idx
                })
        # logger.info(json_format(final_section_list))


        # 备份chunks列表到json文件
        with open(md_path_obj.parent / "chunks.json", 'w', encoding='utf-8') as f:
            f.write(json_format(final_section_list))

        return final_section_list



    def process(self, state: ImportGraphState):
        #第一大步：获取md的内容、文件标题、路径对象
        md_content,file_title,md_path_obj = self.get_md_content(state)

        # 第二大步：对md内容进行按行切割，根据标题合并section，返回的是section列表
        section_list = self.get_section_list(md_content,file_title)

        # 第三大步：对section列表进行精细切分（长切短合），遍历上一步的sction_list
        # 对内容进行去除标题，判断标题符合条件进行切分，构造最终的section,写入part,组成final_section_list
        final_section_list = self.get_final_section_list(section_list,md_path_obj,file_title)

        return {
            "chunks": final_section_list,
        }


if __name__ == '__main__':
    node = NodeDocumentSplit()
    init_state = {
        "md_path":r"D:\output\hak180产品安全手册\hak180产品安全手册_new.md",
        "file_title":"hak180产品安全手册"
    }
    result = node(init_state)
    logger.info(json_format(result))