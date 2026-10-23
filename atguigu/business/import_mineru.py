"""Optional OCR adapter. Remote parser output is untrusted, bounded input.

The API credential is sent only to the configured MinerU origin. Signed upload
and result URLs receive no credential, and archives are never extracted to disk.
"""
from __future__ import annotations

import io
import ipaddress
import re
import socket
import stat
import time
import zipfile
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit
from uuid import uuid4

import httpx

from atguigu.config.config import MineruConfig, RuntimeConfig
from atguigu.business.import_errors import ImportFailure

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_ENTRIES = 500
MAX_MARKDOWN_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def _remote_url(value: str) -> str:
    """Do not let a parser-provided URL point at local infrastructure."""
    try:
        url = urlsplit(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.port not in (None, 443):
            raise ValueError()
        addresses = socket.getaddrinfo(url.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError()
    except (ValueError, OSError):
        raise ValueError("OCR 服务返回的文件地址不符合安全要求") from None
    return value


def _archive_document(data: bytes):
    from atguigu.business.import_parser import ParsedBlock, ParsedDocument, ParsedImage

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("OCR 结果不是有效的解析压缩包") from None
    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES or sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
            raise ValueError("OCR 解析产物数量或解压大小超限")
        files = {}
        for entry in entries:
            path = PurePosixPath(entry.filename)
            raw_name = entry.orig_filename
            if (path.is_absolute() or ".." in path.parts or "\\" in raw_name or ":" in raw_name or "\x00" in raw_name
                    or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
                raise ValueError("OCR 解析压缩包包含非法路径或链接")
            if not entry.is_dir():
                if str(path) in files:
                    raise ValueError("OCR 解析压缩包包含重复路径")
                files[str(path)] = entry
        markdown_names = [name for name in files if PurePosixPath(name).name == "full.md"]
        if len(markdown_names) != 1:
            raise ValueError("OCR 结果缺少唯一的 full.md")
        md_name = markdown_names[0]
        if files[md_name].file_size > MAX_MARKDOWN_BYTES:
            raise ValueError("OCR 正文大小超限")
        content = archive.read(files[md_name]).decode("utf-8-sig")
        images, warnings = [], []
        seen = {}

        def replace_image(match):
            alt, raw = match.group(1), match.group(2).strip().strip("<>")
            # External images are never fetched, and cannot survive into rendered content.
            if urlsplit(raw).scheme or raw.startswith(("/", "\\")):
                warnings.append("OCR 正文中的外部图片未导入")
                return "[图片未导入]"
            relative = PurePosixPath(unquote(raw))
            if ".." in relative.parts or "\\" in raw or ":" in raw:
                raise ValueError("OCR 图片包含非法相对路径")
            name = str(PurePosixPath(md_name).parent / relative)
            entry = files.get(name)
            kind = IMAGE_TYPES.get(relative.suffix.lower())
            if not entry or not kind:
                warnings.append("OCR 结果中的图片缺失或格式不支持")
                return "[图片未导入]"
            if entry.file_size > MAX_IMAGE_BYTES:
                raise ValueError("OCR 图片大小超限")
            if name not in seen:
                marker = "kb-image:" + uuid4().hex
                images.append(ParsedImage(name=relative.name, data=archive.read(entry), content_type=kind, marker=marker))
                seen[name] = marker
            return f"![{alt}]({seen[name]})"

        content = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_image, content)
        content = re.sub(r"<img\b[^>]*>", "[HTML 图片未导入]", content, flags=re.I)
        if not content.strip():
            raise ValueError("OCR 未识别出可用正文")
        return ParsedDocument(blocks=[ParsedBlock(text=content, position={"parser": "mineru", "section": 0})],
                              images=images, warnings=list(dict.fromkeys(warnings)))


def parse_mineru(data: bytes, name: str):
    if not MineruConfig.mineru_token:
        raise ImportFailure("PDF_OCR_CONFIG", "扫描 PDF 需要配置 MINERU_TOKEN，并开启 IMPORT_PDF_OCR")
    headers = {"Authorization": f"Bearer {MineruConfig.mineru_token}"}
    base = MineruConfig.mineru_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=RuntimeConfig.model_timeout, follow_redirects=False) as client:
            response = client.post(base + "/file-urls/batch", headers=headers,
                                   json={"files": [{"name": PurePosixPath(name).name, "data_id": uuid4().hex}],
                                         "model_version": "vlm"})
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise ValueError("OCR 服务未接受该文件")
            urls = payload.get("data", {}).get("file_urls", [])
            batch_id = payload.get("data", {}).get("batch_id")
            if len(urls) != 1 or not isinstance(batch_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", batch_id):
                raise ValueError("OCR 服务返回了无效的任务信息")
            uploaded = client.put(_remote_url(urls[0]), content=data)
            uploaded.raise_for_status()
            deadline = time.monotonic() + MineruConfig.poll_timeout
            result_url = None
            while time.monotonic() < deadline:
                result = client.get(base + "/extract-results/batch/" + batch_id, headers=headers)
                result.raise_for_status()
                payload = result.json()
                if payload.get("code") != 0:
                    raise ValueError("OCR 服务返回解析失败状态")
                results = payload.get("data", {}).get("extract_result", [])
                if results:
                    item = results[0]
                    if item.get("state") == "failed":
                        raise ValueError("OCR 解析失败，请检查扫描文件清晰度或稍后重试")
                    if item.get("state") == "done":
                        result_url = _remote_url(item.get("full_zip_url", ""))
                        break
                time.sleep(min(2, max(0, deadline - time.monotonic())))
            if not result_url:
                raise TimeoutError("OCR 解析超时，可在导入中心重试")
            chunks, size = [], 0
            with client.stream("GET", result_url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(64 * 1024):
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise ValueError("OCR 解析压缩包下载大小超限")
                    chunks.append(chunk)
            return _archive_document(b"".join(chunks))
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise ImportFailure(f"OCR_HTTP_{status}", f"OCR 服务请求失败（HTTP {status}）",
                            status in {408, 429} or status >= 500) from None
    except httpx.RequestError:
        raise ImportFailure("OCR_CONNECTION", "OCR 服务连接失败，请稍后重试", True) from None
    except TimeoutError:
        raise ImportFailure("OCR_TIMEOUT", "OCR 解析超时，可在导入中心重试", True) from None
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile):
        raise ImportFailure("OCR_INVALID_RESULT", "OCR 返回的解析结果无效、超限或含不安全路径") from None
