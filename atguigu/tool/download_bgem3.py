from modelscope.hub.snapshot_download import snapshot_download

# 下载模型到当前目录下的 D:/ai_models/modelscope_cache/models 目录下 但是这个目录不一定是模型所在的目录
# 下载下来可能是一个总的目录，这个总的目录会放到你指定的位置，模型还得从人家总的目录下去找
model_dir = snapshot_download('BAAI/bge-m3', cache_dir='D:/ai_models/modelscope_cache/models')
print(f"模型已下载到: {model_dir}")