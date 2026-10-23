"""Legacy import compatibility; embeddings are always requested from the API."""
from atguigu.tool.embedding_client_tool import get_embeddings

get_bge_m3_embedding = get_embeddings
