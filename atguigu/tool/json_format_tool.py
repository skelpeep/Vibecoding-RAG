import json
import numpy as np

# class NumpyEncoder(json.JSONEncoder):
#     def default(self, obj):
#         if isinstance(obj, np.float16):
#             return float(obj)
#         if isinstance(obj, np.int64):
#             return int(obj)
#         # 可以扩展支持其他 numpy 类型
#         if isinstance(obj, np.integer):
#             return int(obj)
#         if isinstance(obj, np.floating):
#             return float(obj)
#         if isinstance(obj, np.ndarray):
#             return obj.tolist()
#         return super().default(obj)

def json_format(data):
    return json.dumps(data,ensure_ascii=False,indent=4)


