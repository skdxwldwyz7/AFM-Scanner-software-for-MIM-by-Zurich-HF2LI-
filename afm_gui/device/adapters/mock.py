from __future__ import annotations


class MockAdapter:
    def __init__(self, *, capabilities: tuple[str, ...] = ("mock",)) -> None:
        self.capabilities = capabilities

    def snapshot(self) -> dict[str, object]:
        return {
            "adapter": type(self).__name__,
            "capabilities": self.capabilities,
        }

    def close(self) -> None:
        return


__all__ = ["MockAdapter"]
