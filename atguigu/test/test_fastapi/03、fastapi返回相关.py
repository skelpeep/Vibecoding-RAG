import shutil
import uuid

from fastapi import FastAPI, UploadFile, File
from fastapi.params import Path, Query, Depends, Body
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import Response, JSONResponse, FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse

app = FastAPI()

@app.get("/")
def index():
    return {"message": "Hello World"}



# 1、定制的时候采用，平时基本不用
@app.get("/custom")
def custom_response():
    # 返回二进制数据，指定自定义 MIME 类型
    return Response(
        content="<h1>纯文本</h1>",
        # media_type="text/plain",
        media_type="text/html",
        status_code=200)

# 2  JSONResponse  默认返回的数据都会是json格式，只是返回的时候需要额外的数据比如状态码，那么就得写全
# 请求头的信息是给后端传递的信息，是让后端拿到这些信息干活
# 响应头的信息是给前端传递的信息，让浏览器根据这个信息干活
@app.get("/api/user")
def get_user():
    # 等价于直接 return {"name": "张三", "age": 20}（FastAPI 自动转 JSONResponse）
    return JSONResponse(
        content={
            "code":20000,
            "data":{
                "name": "张三",
                "age": 20
            }
        },
        status_code=200,  # 可选，默认 200
        headers={"xxx": "custom-value"}  # 可选，自定义响应头
    )


# 3、当前端需要文件数据，就可以使用，它也是用的比较多
@app.get("/download")
def download():
    return FileResponse(
        r"D:\我的图片\mylove03.png",
        media_type="image/png",
        headers={
            "Content-Disposition": "attachment; filename=mylove03.png"
        }
    )

# 4 了解，以后没有人这么去返回html
@app.get("/hello")
def hello(name: str = "游客"):
    html_content = f"""
    <html>
        <head>
            <!--里面一般都是配置的标签  浏览器的页签标题-->
            <title>我爱杨幂</title>
            <meta charset="utf-8">
        </head>
        <body>
            <!--里面一般是配置的标签 才是浏览器展示的内容 -->
            <h1>你好，{name}！</h1>
            <p>哈哈哈我就是爱杨幂</p>
            <img src="C:\\Users\\admin\\Desktop\\test\\kb_0515\\atguigu\\test\\test_fastapi\\mylove05.png" /> 
            <div>嘿嘿</div>   
        </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)

# 5、了解，基本我们后期都是返回json格式，很少返纯文本除非返回日志
@app.get("/text")
async def get_text():
    return PlainTextResponse(content="<h1>这是纯文本响应</h1>", status_code=200)


#6、了解，重定向
@app.get("/old-path")
async def redirect_old_path():
    # 重定向到 /new-path，状态码 307 表示临时重定向
    return RedirectResponse(url="/new-path", status_code=307)

@app.get("/new-path")
async def new_path():
    return {"message": "这是新接口"}




if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


