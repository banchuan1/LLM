"""界面契约（端口）：core 定义的抽象，各前端目录（tui/web/desktop/mobile）实现它。"""
from abc import ABC, abstractmethod


class BaseUI(ABC):
    """界面基类。

    界面与核心层的唯一耦合点是注入的 agent 对象（core.agent.Agent），
    约定消费 agent.chat_stream(prompt) 这一同步生成器接口。
    新增前端（web/desktop/mobile）时继承本类实现 run()，并在 main.py 注册即可。
    """

    def __init__(self, agent):
        self.agent = agent

    @abstractmethod
    def run(self):
        """启动界面并进入主循环。"""
