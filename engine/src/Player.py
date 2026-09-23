from dataclasses import dataclass
from unittest.mock import Mock
from src.AgentBase import AgentBase as Agent

# C++용 임포트
from copy import deepcopy

@dataclass
class Player:
    name: str
    agent: Agent
    move_time: int = 0
    turn: int = 0

    def __eq__(self, value: object) -> bool:
        if isinstance(self.agent, Mock) and isinstance(value.agent, Mock):
            return (
                self.name == value.name
                and self.move_time == value.move_time
            )
        return (
            hash(self.agent) == hash(value.agent)
            and self.name == value.name
            and self.move_time == value.move_time
        )

# C++ 구동을 위한 Deepcopy 추가
    def __deepcopy__(self, memo):
        # agent 객체(ExternalAgent)는 내부에 프로세스 락(lock)이 있어서 깊은 복사가 불가능함.
        # 따라서 agent는 복사하지 않고 기존 객체를 그대로 참조(Shallow copy)하게 해야함.
        
        new_player = Player(
            name=deepcopy(self.name, memo),
            agent=self.agent,  # 핵심: 여기서 deepcopy를 쓰지 않고 self.agent를 그대로 넘김.
            move_time=deepcopy(self.move_time, memo),
            turn=deepcopy(self.turn, memo)
        )
        return new_player