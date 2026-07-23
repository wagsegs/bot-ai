from abc import ABC, abstractmethod
from typing import Protocol


class AIProvider(Protocol):
    async def chat(self, messages: list[dict]) -> dict: ...


class BaseProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict]) -> dict:
        ...
