"""Shared repository exports."""

from app.common.repositories.base import BaseRepository
from app.common.repositories.search import RelatedSearch

__all__ = ["BaseRepository", "RelatedSearch"]
