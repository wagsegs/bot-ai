from typing import List, Dict


class ConversationSession:
    def __init__(self, user_id: str, channel_id: str) -> None:
        self.user_id = user_id
        self.channel_id = channel_id
        self.messages: List[Dict[str, str]] = []

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def to_prompt_context(self) -> List[Dict[str, str]]:
        return self.messages[-8:]
