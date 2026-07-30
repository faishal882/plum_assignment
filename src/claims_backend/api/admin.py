from datetime import UTC, datetime
from secrets import compare_digest
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request
from wtforms import SelectField

from claims_backend.config import Settings
from claims_backend.domain.identity import Role, normalize_username
from claims_backend.infrastructure.postgres.models import (
    MemberRow,
    UserMemberLinkRow,
    UserRoleRow,
    UserRow,
)

_SESSION_KEY = "claims_sqladmin_username"


class SqlAdminAuthentication(AuthenticationBackend):
    def __init__(self, settings: Settings) -> None:
        if (
            settings.sqladmin_username is None
            or settings.sqladmin_password is None
            or settings.sqladmin_secret_key is None
        ):
            raise ValueError("SQLAdmin credentials are not configured")
        super().__init__(
            secret_key=settings.sqladmin_secret_key,
            same_site="lax",
            https_only=False,
        )
        self._username = settings.sqladmin_username
        self._password = settings.sqladmin_password

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        authenticated = compare_digest(username, self._username) & compare_digest(
            password,
            self._password,
        )
        request.session.clear()
        if authenticated:
            request.session[_SESSION_KEY] = self._username
        return authenticated

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        username = request.session.get(_SESSION_KEY)
        return isinstance(username, str) and compare_digest(username, self._username)


class UserAdmin(ModelView, model=UserRow):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user"
    category = "Identity"
    category_icon = "fa-solid fa-users-gear"

    column_list = [
        UserRow.id,
        UserRow.username,
        UserRow.created_at,
        UserRow.updated_at,
    ]
    column_searchable_list = [UserRow.username, UserRow.normalized_username]
    column_sortable_list = [UserRow.username, UserRow.created_at, UserRow.updated_at]
    column_default_sort = "username"
    form_columns = [UserRow.username]

    can_create = True
    can_edit = True
    can_delete = False
    can_export = False
    can_import = False

    async def on_model_change(
        self,
        data: dict[str, Any],
        model: UserRow,
        is_created: bool,
        request: Request,
    ) -> None:
        del request
        now = datetime.now(UTC)
        normalized = normalize_username(str(data["username"]))
        data["username"] = normalized
        data["normalized_username"] = normalized
        data["updated_at"] = now
        if is_created:
            data["id"] = uuid4()
            data["created_at"] = now
        else:
            data["id"] = model.id
            data["created_at"] = model.created_at


class UserRoleAdmin(ModelView, model=UserRoleRow):
    name = "User Role"
    name_plural = "User Roles"
    icon = "fa-solid fa-user-shield"
    category = "Identity"

    column_list = [UserRoleRow.user_id, UserRoleRow.role]
    column_sortable_list = [UserRoleRow.user_id, UserRoleRow.role]
    form_columns = [UserRoleRow.user_id, UserRoleRow.role]
    form_include_pk = True
    form_overrides = {"role": SelectField}
    form_args = {
        "role": {
            "choices": [(role.value, role.value.title()) for role in Role],
        }
    }

    can_create = True
    can_edit = False
    can_delete = True
    can_export = False
    can_import = False


class UserMemberLinkAdmin(ModelView, model=UserMemberLinkRow):
    name = "Member Link"
    name_plural = "Member Links"
    icon = "fa-solid fa-link"
    category = "Identity"

    column_list = [UserMemberLinkRow.user_id, UserMemberLinkRow.member_id]
    column_searchable_list = [UserMemberLinkRow.member_id]
    column_sortable_list = [UserMemberLinkRow.user_id, UserMemberLinkRow.member_id]
    form_columns = [UserMemberLinkRow.user_id, UserMemberLinkRow.member_id]
    form_include_pk = True

    can_create = True
    can_edit = False
    can_delete = True
    can_export = False
    can_import = False


class MemberAdmin(ModelView, model=MemberRow):
    name = "Policy Member"
    name_plural = "Policy Members"
    icon = "fa-solid fa-address-card"
    category = "Identity"

    column_list = [
        MemberRow.id,
        MemberRow.policy_id,
        MemberRow.external_member_id,
        MemberRow.created_at,
    ]
    column_searchable_list = [MemberRow.policy_id, MemberRow.external_member_id]
    column_sortable_list = [
        MemberRow.policy_id,
        MemberRow.external_member_id,
        MemberRow.created_at,
    ]
    column_default_sort = [
        (MemberRow.policy_id, False),
        (MemberRow.external_member_id, False),
    ]

    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
    can_import = False


def install_sqladmin(
    app: FastAPI,
    engine: AsyncEngine,
    settings: Settings,
) -> Admin | None:
    if not settings.sqladmin_enabled:
        return None

    admin = Admin(
        app=app,
        engine=engine,
        base_url="/admin",
        title="Plum Claims Administration",
        authentication_backend=SqlAdminAuthentication(settings),
    )
    admin.add_view(UserAdmin)
    admin.add_view(UserRoleAdmin)
    admin.add_view(UserMemberLinkAdmin)
    admin.add_view(MemberAdmin)
    return admin
