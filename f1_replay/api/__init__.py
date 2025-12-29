"""
F1 Race Viewer Flask API

Provides optimized 3-tier API endpoints:
- /api/seasons - Season catalog
- /api/weekend/<year>/<round> - Weekend metadata + circuit geometry
- /api/session/<year>/<round>/<session_type> - Complete session data
"""

from f1_replay.api.app import create_app

__all__ = ['create_app']
