from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.keyboards import admin_menu, participant_menu
from app.bot.routers import build_router
from app.config import Settings
from app.models import Base, User
from app.services.admin_drafts import delete_admin_draft, get_admin_draft, save_admin_draft


@pytest.fixture
async def session_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test_handlers.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_keyboards_structure():
    user_menu = participant_menu(is_admin=False)
    button_texts = [btn.text for row in user_menu.keyboard for btn in row]
    assert "📝 نظرسنجی‌های فعال" in button_texts
    assert "📊 امتیازهای من" in button_texts
    assert "↩️ بازگشت به پنل مدیر" not in button_texts

    evaluator_menu = participant_menu(is_admin=True)
    evaluator_buttons = [btn.text for row in evaluator_menu.keyboard for btn in row]
    assert "↩️ بازگشت به پنل مدیر" in evaluator_buttons

    adm_menu = admin_menu(is_owner=False)
    adm_buttons = [btn.text for row in adm_menu.keyboard for btn in row]
    assert "👥 مدیریت افراد" in adm_buttons
    assert "🗳 مدیریت نظرسنجی‌ها" in adm_buttons
    assert "🛡 مدیریت مدیران" not in adm_buttons

    owner_menu = admin_menu(is_owner=True)
    owner_buttons = [btn.text for row in owner_menu.keyboard for btn in row]
    assert "🛡 مدیریت مدیران" in owner_buttons
    assert "📜 وقایع سیستم" in owner_buttons


@pytest.mark.asyncio
async def test_admin_draft_persistence_and_cleanup(session_factory):
    # Save draft
    await save_admin_draft(
        session_factory,
        platform="telegram",
        platform_user_id=123,
        draft_type="person",
        step="PersonWizard:first_name",
        payload={"internal_id": "P-10"},
    )

    draft = await get_admin_draft(
        session_factory,
        platform="telegram",
        platform_user_id=123,
    )
    assert draft is not None
    assert draft.draft_type == "person"
    assert draft.step == "PersonWizard:first_name"
    assert draft.payload["internal_id"] == "P-10"

    # Delete draft
    await delete_admin_draft(
        session_factory,
        platform="telegram",
        platform_user_id=123,
    )
    draft_deleted = await get_admin_draft(
        session_factory,
        platform="telegram",
        platform_user_id=123,
    )
    assert draft_deleted is None


@pytest.mark.asyncio
async def test_platform_isolation_users(session_factory):
    async with session_factory() as session:
        u_tg = User(platform="telegram", platform_user_id=555, full_name="کاربر تلگرام")
        u_bale = User(platform="bale", platform_user_id=555, full_name="کاربر بله")
        session.add_all([u_tg, u_bale])
        await session.commit()

    async with session_factory() as session:
        users = (await session.scalars(select(User).where(User.platform_user_id == 555))).all()
        assert len(users) == 2
        platforms = {u.platform for u in users}
        assert platforms == {"telegram", "bale"}


@pytest.mark.asyncio
async def test_fallback_router_handlers(session_factory):
    settings = Settings(bot_token="test:token", bot_platform="telegram", admin_user_ids="999")
    router = build_router(session_factory, settings)

    for r in router.sub_routers:
        if r.name == "fallback":
            fake_msg = AsyncMock()
            fake_msg.text = "پیام ناشناخته"
            await r.message.handlers[-1].call(fake_msg)
            fake_msg.answer.assert_called_with(
                "این پیام را نمی‌شناسم. از گزینه‌های منو استفاده کنید یا /start را بفرستید."
            )

            fake_cb = AsyncMock()
            fake_cb.data = "stale:random:data"
            await r.callback_query.handlers[-1].call(fake_cb)
            fake_cb.answer.assert_called_with(
                "این دکمه دیگر فعال نیست. از منو دوباره انتخاب کنید.", show_alert=True
            )
