"""Flask blueprints: auth, user, admin and the JSON API."""
from __future__ import annotations

from typing import cast

from flask import current_app

from ..config import Config
from ..services import AdminService, AuthService, BankingService


def get_cfg() -> Config:
    return cast(Config, current_app.extensions["ctpb"]["cfg"])


def get_auth() -> AuthService:
    return cast(AuthService, current_app.extensions["ctpb"]["auth"])


def get_banking() -> BankingService:
    return cast(BankingService, current_app.extensions["ctpb"]["banking"])


def get_admin() -> AdminService:
    return cast(AdminService, current_app.extensions["ctpb"]["admin"])
