from fastapi import  FastAPI

app = FastAPI(
    title="测试",
    description="这是一个测试的后端服务api接口服务器",
    version="0.1.0",
)

@app.get("/")
def index():
    return {"message": "我爱你杨幂"}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )


