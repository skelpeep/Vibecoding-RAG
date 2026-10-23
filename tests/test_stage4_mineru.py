"""OCR archive safety is tested without a remote provider or model substitute."""
import io
import zipfile

import pytest

from atguigu.business import import_mineru as ocr


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as stream:
        for name, content in files.items():
            info = zipfile.ZipInfo(name)
            info.filename = name  # Preserve deliberately unsafe fixture names on Windows.
            stream.writestr(info, content)
    return buffer.getvalue()


def test_ocr_retains_text_and_image_for_authenticated_storage():
    result = ocr._archive_document(archive({"result/full.md": "# 测试\n![图示](images/a.png)",
                                          "result/images/a.png": b"image-test-data"}))
    assert result.blocks[0].text.startswith("# 测试")
    assert len(result.images) == 1
    assert result.images[0].marker in result.blocks[0].text
    assert result.images[0].data == b"image-test-data"
    assert result.blocks[0].position["parser"] == "mineru"


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/windows.txt", "folder\\escape.txt"])
def test_archive_rejects_unsafe_paths(name):
    with pytest.raises(ValueError):
        ocr._archive_document(archive({"full.md": "text", name: "bad"}))


def test_external_images_are_not_preserved_or_requested():
    result = ocr._archive_document(archive({"full.md": '# 正文\n![x](https://127.0.0.1/private)\n<img src="https://evil.invalid/a">'}))
    assert not result.images
    assert "https://" not in result.blocks[0].text
    assert result.warnings


def test_expansion_bound_checked_before_read(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_EXPANDED_BYTES", 10)
    with pytest.raises(ValueError, match="超限"):
        ocr._archive_document(archive({"full.md": "a" * 11}))


@pytest.mark.parametrize("url", ["http://example.org/a", "https://127.0.0.1/a", "https://[::1]/a",
                                "https://user:password@example.org/a", "file:///x"])  # repository-check: allow-credential-url
def test_parser_urls_reject_local_and_credentialed_targets(url):
    with pytest.raises(ValueError):
        ocr._remote_url(url)
