from abc import ABC,abstractmethod

from atguigu.tool.logger import logger


# 这个类我们其实目的是想要做一个接口规范，它是一个抽象类，目的是为了让后面所有的节点类必须继承我这个类
# 来接受我定义的规范

class NodeBase(ABC):
    name = "node_base"


    def __init__(self):
        if self.name == "node_base":
            raise Exception(f"子类{self.__class__.__name__}必须重写父类的name属性")


    @abstractmethod
    def process(self,state):
        pass


    def __call__(self, state):
        # 1、可以实现每个节点调用统一打印日志
        # 2、可以统一进行异常捕获

        try:
            logger.info(f"{self.name}开始执行了")
            # 这个call是后期所有的子类对象在当函数使用的时候，都会自动调用这个方法
            result = self.process(state)
            logger.info(f"{self.name}执行结束了")
            return result
        except Exception as e:
            logger.error(f"{self.name}执行异常了")
            raise e










