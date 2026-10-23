"""Explicit download only; importing this module never downloads a model."""
from atguigu.config.config import EmbeddingConfig

def main():
    from huggingface_hub import snapshot_download
    model_dir = snapshot_download(EmbeddingConfig.bge_m3, local_dir=EmbeddingConfig.bge_m3_path)
    print(f"模型已下载到: {model_dir}")

if __name__ == "__main__":
    main()
