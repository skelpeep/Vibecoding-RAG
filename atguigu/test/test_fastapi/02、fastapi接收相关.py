import shutil
import uuid

from fastapi import FastAPI, UploadFile, File
from fastapi.params import Path, Query, Depends, Body
from pydantic import BaseModel, Field
from starlette.requests import Request

app = FastAPI()

@app.get("/")
def index():
    return {"message": "Hello World"}

# 1、接收路径参数  路径参数是站url的一部分,而且传递了必须占位
# Path里面我们关注限定的几个参数 ...代表必须传递 default代表默认值，只是路径参数必须传递
# 所以在Path当中一般不写default，description对参数进行描述
@app.get("/testpath/{id}/{name}/{age}",summary="测试路径参数")
def testpath(
        id: int,
        name: str = "yangmi", #路径参数必须传递 写默认值没什么意义
        age: int = Path(...,description="年龄",ge=0,le=120)
):
    return {"id": id, "name": name, "age": age}



# 2、接收查询参数  必传和默认值是互斥的
@app.get("/testquery")
def testquery(
        id: int, #默认必须传递否则炸
        height: float = 180, #默认传递180 可传可不传
        gender: str = Query(...,description="性别"),
        name: str = Query(default="yangmi",description="姓名")
):
    return {"id": id, "height": height, "gender": gender, "name": name}


# 3、请求体参数是挑请求方式 一般get和delete不常用 没有人传请求体
# 只有post和put才会用到请求体参数
# 请求体参数一般都是json json前端传递的一般都是对象或者对象的数组（字典或者字典列表/对象或者对象列表）
# BaseModel是pydantic库里面的一个基类，用来做数据校验的，最终其实我们是通过这个类的对象去接收的参数
# 只要是json请求体参数，BaseModel就是专门针对这些参数的
# 1、会实例化一个对象
# 2、校验传递的json和定义的类当中是否匹配
# 3、返回实例化的对象
class User(BaseModel):
    username: str = Field(...,description="用户名")
    password: str = Field(description="用户名",default="111111")

@app.post("/testbody")
def testbody(user: User):
    print(user,type(user))
    return user


# 4、接收混合参数  路径查询请求体一起传递(第一种接收方式)
# @app.post("/testmixed/{id}")
# def testmixed(
#     user: User,
#     id: int = Path(...,description="用户id"),
#     name: str = Query(...,description="姓名"),
#     age: int = Query(default=18,description="年龄"),
# ):
#     return {"id": id, "name": name, "age": age, "user": user}

# 5、接收混合参数  路径查询请求体一起传递(第二种接收方式)
# 使用BaseModel类去解决请求体，使用普通类去解决路径和查询参数（键值对参数）
# 依赖注入给了一个Depends类，使用它传递一个类或者函数（可以调用的东西），会自动去调用传递的类或者函数，并且fastapi会自动识别所有的参数
# 进行自动注入
# 普通类去解决路径和查询参数，需要依赖注入才可以
class Student:
    def __init__(self,id:int=None,name:str=None,age:int=18):
        self.id = id
        self.name = name
        self.age = age


@app.post("/testmixed/{id}")
def testmixed(
    user: User = Body(...,description="用户请求体信息"),
    student: Student = Depends(Student)
):
    return {"id": student.id, "name": student.name, "age": student.age, "user": user}



# 6、接收请求头的信息
@app.get("/testheader")
def testheader(request: Request):
    # request.headers
    print(request.headers.get("token"))
    return {"message": "Hello World"}

# 7、接收文件
# 接受formData的数据，文件上传，文件上传是表单提交的一种方式
@app.post("/upload")
def upload(file:UploadFile = File(...,description="上传文件")):
    print(file.filename)
    print(file.size)
    print(file.content_type)
    print(file.file)
    print(file.headers)

    # 这里我们拿到文件之后，需要把文件保存到磁盘，然后转储到对象容器当中（minio）
    dir_path = "./"
    file_name = str(uuid.uuid4())[:9] + file.filename #随机的一个全宇宙唯一的标识字符串
    fs = open(dir_path + "/" + file_name,"wb")
    shutil.copyfileobj(file.file,fs,1024*1024)
    fs.close()

    # 转储自己去做，转储后拿到网络路径（minio的图片路径）
    return {"file": file.filename,"url":"后期自己做"}













if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


