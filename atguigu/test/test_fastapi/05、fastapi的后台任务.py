#它的作用就是让用户发请求，立即响应，中间的一些 耗时操作，交给后台去执行
# 我们看起来请求已经结束了，实际上后台还在干活
import time

from fastapi import FastAPI, BackgroundTasks

app = FastAPI()


@app.get("/")
async def index():
    return {"message": "Hello World"}


def generate_love(n,name):
    while n > 0:
        n -= 1
        print("i love you" + name)
        time.sleep(1)

@app.get("/testbackgroundtasks")
async def testbackgroundtasks(backgroundtasks: BackgroundTasks):

    backgroundtasks.add_task(generate_love,10,name="杨幂")

    return {"message": "hello world"}



if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


