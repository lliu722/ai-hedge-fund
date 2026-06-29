from src.adapters.base import Adapter


class LLMAdapter(Adapter):
    def __init__(self) -> None:
        self.on_failure = "return empty string; calling lens degrades to 'lens unavailable'"
        super().__init__()

    def fetch(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 600,
        temperature: float = 0.3,
    ) -> str:
        from src.tools.llm import call_deepseek

        result = call_deepseek(
            prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not result or result.startswith("❌"):
            return ""
        return result
