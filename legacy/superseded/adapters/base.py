from abc import ABC, abstractmethod


class AdapterError(Exception):
    pass


class Adapter(ABC):
    on_failure: str

    def __init__(self) -> None:
        if not getattr(self, "on_failure", ""):
            raise AdapterError("Adapter subclasses must set on_failure in __init__")

    @abstractmethod
    def fetch(self, *args, **kwargs):
        pass
