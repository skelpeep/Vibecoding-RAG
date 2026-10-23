"""Reproduce small, explicitly labelled parser/permission demonstration inputs."""
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples/stage4"


def text_pdf(lines):
    """Minimal valid text PDF; ASCII avoids depending on installed font packages."""
    content = "BT /F1 14 Tf 50 790 Td 22 TL\n" + "\n".join(
        "(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj T*" for line in lines) + "\nET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               f"<< /Length {len(content.encode())} >>\nstream\n{content}\nendstream".encode()]
    data, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for i, value in enumerate(objects, 1):
        offsets.append(len(data)); data.extend(f"{i} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "技术变更流程.md").write_text("# 技术变更流程（示例）\n\n仅供阶段四导入和权限演示，不是正式制度。\n\n## 提交与复核\n变更负责人应记录影响范围、验证方法与回退步骤。\n常规变更至少提前一个工作日提交，由技术部复核。\n\n## 完成记录\n执行完成后补充结果与异常处理记录。\n", encoding="utf-8")
    (OUT / "客户资料交接.txt").write_text("客户资料交接（示例）\n仅供测试，不是正式业务制度。\n交接清单包含负责人、交接日期、资料版本和访问范围。\n接收人确认清单后，归档已签收记录。\n", encoding="utf-8")
    paragraphs = ["知识发布检查（示例）", "本文件用于 DOCX 解析演示，不是正式制度。", "发布前核对标题、正文、附件及数据访问范围。", "索引完成后先激活版本，再发布知识。失败时保留现有版本。"]
    with ZipFile(OUT / "知识发布检查.docx", "w") as doc:
        doc.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        doc.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        doc.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>' + "".join("<w:p><w:r><w:t>" + escape(s) + "</w:t></w:r></w:p>" for s in paragraphs) + "<w:sectPr/></w:body></w:document>")
    (OUT / "release-checklist.pdf").write_bytes(text_pdf(["Release checklist (DEMO)", "This document is a parser test, not a company policy.", "1. Review content, attachments and access grants.", "2. Wait until the new version is ready.", "3. Activate the version, then publish the unit.", "4. Preserve the active version when indexing fails."]))
    (OUT / "README.md").write_text("# 阶段四示例输入\n\n此目录的 Markdown、TXT、DOCX 和文字 PDF 是明确标注的测试材料，不是正式组织制度。可运行 `python scripts/create_stage4_examples.py` 重建。\n\n将四份业务文件在导入中心一起上传；不要选本 README。导入完成仅表示版本索引可用，授权、激活与发布均需显式操作。\n", encoding="utf-8")
    print("Created 4 labelled document examples and README under examples/stage4")


if __name__ == "__main__":
    main()
