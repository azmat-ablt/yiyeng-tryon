from fastapi import Request

from .jobs import JobManager
from .library import Library
from .storage import LocalStorage
from .store import AssetStore


def get_storage(request: Request) -> LocalStorage:
    return request.app.state.storage


def get_asset_store(request: Request) -> AssetStore:
    return request.app.state.assets


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.jobs


def get_library(request: Request) -> Library:
    return request.app.state.library
