# 案例1
# 	1、客户前端发ajax请求要发邮件并携带session_id，服务端直接回复收到，制造邮件开始
# 	2、服务端就开始执行backgroundtasks当中造邮件的函数，造的邮件全部放在队列当中
# 	3、客户端想直接拿到造的邮件内容，造一个拿一个，那么客户端需要去发送订阅sse请求
# 	4、服务端需要写sse回复接口，流式返回，流式返回就是把一个生成器对象返回
# 		生成器函数当中就是从queue_dict当中获取自己session_id的队列，从队列当中一个一个yield球
# 注意：每个session_id对应自己的邮件队列
import time

import uvicorn
from fastapi import FastAPI, BackgroundTasks
from fastapi.params import Query
from starlette.middleware.cors import CORSMiddleware
from queue import Queue

from starlette.responses import StreamingResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

queue_dict = {}

def make_email(session_id:str):
    global queue_dict
    # 1、若该session_id无队列，则创建
    if not queue_dict.get(session_id):
        queue_dict[session_id] = Queue()

    q = queue_dict.get(session_id)

    # 2、往队列中放入邮件数据
    q.put("我爱杨幂01")
    q.put("我爱杨幂02")
    q.put("我爱杨幂03")
    q.put("我爱杨幂04")
    q.put("我爱杨幂05")
    q.put(None)  # 3、None作为结束标识






@app.get("/sse01")
async def sse01(
        background_tasks: BackgroundTasks,
        session_id:str = Query(...,description="会话id")
):

    # 调用后台任务去造邮件
    background_tasks.add_task(make_email, session_id=session_id)

    return {"message":"收到，立马给您造邮件存储"}



@app.get("/stream")
async def stream(session_id:str = Query(...,description="会话id") ):

    def get_email():
        # 拿队列准备取邮件
        while not queue_dict.get(session_id):
            time.sleep(3)

        q = queue_dict.get(session_id)
        while True:
            email = q.get()
            yield f"data:{email}\n\n"
            if email is None:
                break
            time.sleep(1)

    return StreamingResponse(get_email(),media_type="text/event-stream")







if __name__ == '__main__':
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )

