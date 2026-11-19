from ..config import Settings
from .base import TryOnProvider
from .local import LocalProvider
from .remote import RemoteProvider
from .stub import StubProvider


def build_provider(settings: Settings) -> TryOnProvider:
    name = settings.inference_provider.lower()
    if name == "stub":
        return StubProvider()
    if name == "local":
        return LocalProvider(settings.local_inference_url)
    if name == "remote":
        return RemoteProvider(settings.remote_api_url, settings.remote_api_key)
    raise ValueError(f"未知的推理方案: {settings.inference_provider}")
