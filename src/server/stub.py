"""Explicit demonstration engine for B1; never a real-model fallback."""

from b2_core.contracts import CoreReply, CoreRequest


class StubEngine:
    """Fixed, visibly labelled output without model or network dependencies."""

    is_mock: bool = True
    model_version: str = "stub-b1"

    def generate(self, request: CoreRequest) -> CoreReply:
        return CoreReply(
            reply="【演示数据】这是 B1 固定示例回复，尚未调用真实模型。",
            emotion="unknown",
            expression="listening",
            model_version=self.model_version,
            is_mock=self.is_mock,
        )
