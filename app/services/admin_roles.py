from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminRole, AdminUser, User
from app.services.audit import record_audit_log


class AdminRoleError(ValueError):
    """Raised for unauthorized or invalid admin role modifications."""


async def bootstrap_initial_admins(
    session: AsyncSession,
    platform: str,
    initial_admin_ids: set[int],
) -> None:
    if not initial_admin_ids:
        return
    existing = set(
        (
            await session.scalars(
                select(AdminUser.platform_user_id).where(AdminUser.platform == platform)
            )
        ).all()
    )
    for user_id in initial_admin_ids:
        if user_id not in existing:
            session.add(
                AdminUser(
                    platform=platform,
                    platform_user_id=user_id,
                    role=AdminRole.OWNER.value,
                )
            )
    await session.commit()


async def get_user_role(
    session: AsyncSession,
    *,
    platform: str,
    platform_user_id: int,
    initial_admin_ids: set[int] | None = None,
) -> AdminRole | None:
    admin = await session.scalar(
        select(AdminUser).where(
            AdminUser.platform == platform,
            AdminUser.platform_user_id == platform_user_id,
        )
    )
    if admin is not None:
        return AdminRole(admin.role)

    # Check if the user is in initial_admin_ids and bootstrap if so
    if initial_admin_ids and platform_user_id in initial_admin_ids:
        new_admin = AdminUser(
            platform=platform,
            platform_user_id=platform_user_id,
            role=AdminRole.OWNER.value,
        )
        session.add(new_admin)
        await session.commit()
        return AdminRole.OWNER

    return None


async def list_admin_users(
    session: AsyncSession,
    *,
    platform: str,
    initial_admin_ids: set[int] | None = None,
) -> list[AdminUser]:
    if initial_admin_ids:
        await bootstrap_initial_admins(session, platform, initial_admin_ids)
    admins = (
        await session.scalars(
            select(AdminUser)
            .where(AdminUser.platform == platform)
            .order_by(AdminUser.role.desc(), AdminUser.created_at.asc())
        )
    ).all()
    return list(admins)


async def add_admin_user(
    session: AsyncSession,
    *,
    platform: str,
    platform_user_id: int,
    role: AdminRole,
    actor_id: int,
    initial_admin_ids: set[int] | None = None,
) -> AdminUser:
    if initial_admin_ids:
        await bootstrap_initial_admins(session, platform, initial_admin_ids)

    existing = await session.scalar(
        select(AdminUser).where(
            AdminUser.platform == platform,
            AdminUser.platform_user_id == platform_user_id,
        )
    )
    if existing:
        raise AdminRoleError(f"کاربر با شناسهٔ {platform_user_id} در حال حاضر دسترسی مدیریتی دارد.")

    new_admin = AdminUser(
        platform=platform,
        platform_user_id=platform_user_id,
        role=role.value,
    )
    session.add(new_admin)
    # Sync is_admin in users table if exists
    await session.execute(
        update(User)
        .where(User.platform == platform, User.platform_user_id == platform_user_id)
        .values(is_admin=True)
    )
    await session.commit()

    await record_audit_log(
        session,
        platform=platform,
        actor_id=actor_id,
        action="ADMIN_ADD",
        target_type="admin_user",
        target_id=str(platform_user_id),
        details={"role": role.value},
    )
    return new_admin


async def update_admin_role(
    session: AsyncSession,
    *,
    platform: str,
    platform_user_id: int,
    new_role: AdminRole,
    actor_id: int,
    initial_admin_ids: set[int] | None = None,
) -> AdminUser:
    if initial_admin_ids:
        await bootstrap_initial_admins(session, platform, initial_admin_ids)

    admin = await session.scalar(
        select(AdminUser).where(
            AdminUser.platform == platform,
            AdminUser.platform_user_id == platform_user_id,
        )
    )
    if not admin:
        raise AdminRoleError("مدیر موردنظر یافت نشد.")

    if admin.role == AdminRole.OWNER.value and new_role != AdminRole.OWNER:
        # Check that there is at least one other owner
        owner_count = await session.scalar(
            select(func.count(AdminUser.id)).where(
                AdminUser.platform == platform,
                AdminUser.role == AdminRole.OWNER.value,
            )
        )
        if (owner_count or 0) <= 1:
            raise AdminRoleError("حذف یا تغییر نقش آخرین مالک مجاز نیست.")

    old_role = admin.role
    admin.role = new_role.value
    await session.commit()

    await record_audit_log(
        session,
        platform=platform,
        actor_id=actor_id,
        action="ADMIN_ROLE_CHANGE",
        target_type="admin_user",
        target_id=str(platform_user_id),
        details={"old_role": old_role, "new_role": new_role.value},
    )
    return admin


async def remove_admin_user(
    session: AsyncSession,
    *,
    platform: str,
    platform_user_id: int,
    actor_id: int,
    initial_admin_ids: set[int] | None = None,
) -> None:
    if initial_admin_ids:
        await bootstrap_initial_admins(session, platform, initial_admin_ids)

    admin = await session.scalar(
        select(AdminUser).where(
            AdminUser.platform == platform,
            AdminUser.platform_user_id == platform_user_id,
        )
    )
    if not admin:
        raise AdminRoleError("مدیر موردنظر یافت نشد.")

    if admin.role == AdminRole.OWNER.value:
        owner_count = await session.scalar(
            select(func.count(AdminUser.id)).where(
                AdminUser.platform == platform,
                AdminUser.role == AdminRole.OWNER.value,
            )
        )
        if (owner_count or 0) <= 1:
            raise AdminRoleError("حذف آخرین مالک مجاز نیست.")

    old_role = admin.role
    await session.delete(admin)
    # Sync is_admin in users table if exists
    await session.execute(
        update(User)
        .where(User.platform == platform, User.platform_user_id == platform_user_id)
        .values(is_admin=False)
    )
    await session.commit()

    await record_audit_log(
        session,
        platform=platform,
        actor_id=actor_id,
        action="ADMIN_REMOVE",
        target_type="admin_user",
        target_id=str(platform_user_id),
        details={"removed_role": old_role},
    )
