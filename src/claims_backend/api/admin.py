from datetime import UTC, datetime
from secrets import compare_digest
from types import new_class
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request
from wtforms import SelectField

from claims_backend.config import Settings
from claims_backend.domain.identity import Role, normalize_username
from claims_backend.infrastructure.postgres.models import (
    Base,
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


class ReadOnlyDataAdmin(ModelView):
    icon = "fa-solid fa-database"
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
    can_import = False
    page_size = 25
    page_size_options = [25, 50, 100]


_MANAGED_IDENTITY_MODELS = {UserRow, UserRoleRow, UserMemberLinkRow, MemberRow}
_SCALAR_SORT_TYPES = (BigInteger, Boolean, Date, DateTime, Float, Integer, String)
_TEXT_SEARCH_TYPES = (String, Text)
_CATEGORY_BY_TABLE_PREFIX = {
    "audit": "Audit",
    "casefile": "Adjudication",
    "claim": "Claims",
    "component": "Workflow",
    "decision": "Adjudication",
    "document": "Documents",
    "evidence": "Evidence",
    "identity": "Evidence",
    "idempotency": "Claims",
    "import": "Policy Setup",
    "member": "Policy Setup",
    "model": "Evidence",
    "ocr": "Documents",
    "policy": "Policy Setup",
    "processing": "Workflow",
    "review": "Review",
    "rule": "Adjudication",
    "setup": "Policy Setup",
    "workflow": "Workflow",
}


def _humanize_table_name(table_name: str) -> str:
    words = table_name.replace("_", " ").title().split()
    acronyms = {"Id": "ID", "Ocr": "OCR"}
    return " ".join(acronyms.get(word, word) for word in words)


def _category_for_table(table_name: str) -> str:
    prefix = table_name.split("_", maxsplit=1)[0]
    return _CATEGORY_BY_TABLE_PREFIX.get(prefix, "Data")


def _model_columns(model: type[Base], *, include_binary: bool) -> list[Any]:
    columns = []
    for column in model.__table__.columns:
        if not include_binary and isinstance(column.type, LargeBinary):
            continue
        columns.append(getattr(model, column.name))
    return columns


def _searchable_columns(model: type[Base]) -> list[Any]:
    return [
        getattr(model, column.name)
        for column in model.__table__.columns
        if isinstance(column.type, _TEXT_SEARCH_TYPES)
    ]


def _sortable_columns(model: type[Base]) -> list[Any]:
    return [
        getattr(model, column.name)
        for column in model.__table__.columns
        if isinstance(column.type, _SCALAR_SORT_TYPES)
    ]


def _build_read_only_admin_view(model: type[Base]) -> type[ReadOnlyDataAdmin]:
    table_name = model.__tablename__
    display_name = _humanize_table_name(table_name.removesuffix("s"))
    namespace = {
        "name": display_name,
        "name_plural": _humanize_table_name(table_name),
        "category": _category_for_table(table_name),
        "column_list": _model_columns(model, include_binary=False),
        "column_details_list": _model_columns(model, include_binary=True),
        "column_searchable_list": _searchable_columns(model),
        "column_sortable_list": _sortable_columns(model),
    }
    return new_class(
        f"{model.__name__.removesuffix('Row')}Admin",
        (ReadOnlyDataAdmin,),
        {"model": model},
        lambda ns: ns.update(namespace),
    )


def _read_only_admin_views() -> list[type[ReadOnlyDataAdmin]]:
    models = [
        mapper.class_
        for mapper in Base.registry.mappers
        if mapper.class_ not in _MANAGED_IDENTITY_MODELS
    ]
    return [
        _build_read_only_admin_view(model)
        for model in sorted(models, key=lambda m: m.__tablename__)
    ]


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
    for view in _read_only_admin_views():
        admin.add_view(view)
    return admin
