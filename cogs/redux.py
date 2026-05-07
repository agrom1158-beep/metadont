from __future__ import annotations

import disnake
from disnake.ext import commands

# ==========================================
# КОНСТАНТЫ ДЛЯ ДИЗАЙНА
# ==========================================
SKY_BLUE = 0x87CEEB
INVISIBLE_COLOR = 0x2B2D31

# ==========================================
# ВСЕ ЭМОДЗИ В ОДНОМ БЛОКЕ — МЕНЯЙ ЗДЕСЬ
# ==========================================
# Можно подставлять как стандартные эмодзи (например, "🛡️"),
# так и кастомные дискордовские в формате "<:name:id>" / "<a:name:id>".
EMOJIS: dict[str, str] = {
    "REDUX": "🛡️",
    "GUN": "🔫",
    "SOUND": "🎧",
    "BUG": "🐞",
    "IDEA": "💡",
    "FILE": "📁",
    "DOWNLOAD": "📥",
    "UNZIP": "🗃️",
    "STEAM": "🎮",
    "EPIC": "🕹️",
    "INFO": "ℹ️",
    "RETICLE": "🎯",
    "WARNING": "⚠️",
    "POINT": "●",
    "FAMILY": "👨‍👩‍👧",
    "STYLE": "✨",
    "SHIELD_CHECK": "🛡️",
    "ARROW": "➡️",
}

# ==========================================
# ССЫЛКИ И ИЗОБРАЖЕНИЯ — МЕНЯЙ ЗДЕСЬ
# ==========================================
# Главный баннер для панели в канале (опционально, можно оставить "").
REDUX_BANNER_URL: str = ""

# --- Spartan Redux ---
# Картинка, которая показывается в эфемерном сообщении при выборе Spartan Redux.
# Пользователь дозаполнит вручную.
SPARTAN_REDUX_IMAGE_URL: str = ""
SPARTAN_REDUX_DRIVE_URL: str = (
    "https://drive.google.com/drive/folders/1z42qr70F6dRZJ7YW5Ze-A6nFZxXQJeXG"
)

# --- Gunpack: 3 части, у каждой своя картинка и ссылка ---
GUNPACK_PARTS: list[dict[str, str]] = [
    {
        "title": "Gunpack — Часть 1",
        "image": (
            "https://media.discordapp.net/attachments/1478886124775538811/"
            "1501883904146014268/content.png?ex=69fdb1e2&is=69fc6062&hm="
            "1ce19a7297cebb93c3558b4ac3c4bf8c1120d3f43aab700538646d8a6126c4c6"
            "&=&format=webp&quality=lossless&width=525&height=350"
        ),
        "drive": "https://drive.google.com/drive/folders/1NVD3qUT-tjYQkXFtpLISfoWZxmAwVjf8",
    },
    {
        "title": "Gunpack — Часть 2",
        "image": (
            "https://media.discordapp.net/attachments/1478886124775538811/"
            "1501885717515599892/image.png?ex=69fdb392&is=69fc6212&hm="
            "8e60634999440b48ffaa3bb9b486dfda5af90f15050c852d03e727db8ccb2751"
            "&=&format=webp&quality=lossless&width=525&height=350"
        ),
        "drive": "https://drive.google.com/drive/folders/1E8UWOVbfyxO_LoPMLH4MzRVgRGt3MP4J?usp=sharing",
    },
    {
        "title": "Gunpack — Часть 3",
        "image": (
            "https://media.discordapp.net/attachments/1478886124775538811/"
            "1501886135864135690/content.png?ex=69fdb3f6&is=69fc6276&hm="
            "1c7a3234f107ddacea8f33ccabd794762c385019c0b9dd5eca22620cdb9c641c"
            "&=&format=webp&quality=lossless&width=1376&height=917"
        ),
        "drive": "https://drive.google.com/drive/folders/1PfuOd2rDod9z66bBf21c2PZ7957By2g-?usp=sharing",
    },
]

# --- Sound ---
SOUND_IMAGE_URL: str = ""
SOUND_DRIVE_URL: str = (
    "https://drive.google.com/drive/folders/13DyUD361uiJwIL_l1jFi4I30yb1Kmzxc?usp=sharing"
)

# --- Канал, куда улетают сообщения «Ошибка / Идея» ---
# ВПИШИ СВОЙ ID ВРУЧНУЮ
BUG_REPORT_CHANNEL_ID: int = 0  # например 1234567890123456789

# ==========================================
# PERSISTENT CUSTOM IDS
# ==========================================
REDUX_SELECT_CID = "redux_action_select"
REDUX_OPT_SPARTAN = "redux_spartan"
REDUX_OPT_GUNPACK = "redux_gunpack"
REDUX_OPT_SOUND = "redux_sound"
REDUX_OPT_BUG = "redux_bug"

REDUX_BUG_MODAL_CID = "redux_bug_modal"


# ==========================================
# ПОМОЩНИК ДЛЯ ЭМОДЗИ
# ==========================================
def e(key: str) -> str:
    """Возвращает эмодзи с пробелом или пустоту, если эмодзи нет."""
    val = EMOJIS.get(key, "")
    return f"{val} " if val else ""


def e_btn(key: str):
    """Эмодзи без пробела для кнопок/опций селекта (или None)."""
    val = EMOJIS.get(key, "")
    return val if val else None


# ==========================================
# COMPONENTS V2: ГЛАВНАЯ ПАНЕЛЬ В КАНАЛЕ
# ==========================================
def build_redux_panel() -> list[disnake.ui.Container]:
    """Сборка панели Redux одним Container'ом (Components V2):
    баннер, текст, разделители и Select Menu — всё в одном контейнере.
    """
    children: list = []

    if REDUX_BANNER_URL:
        children.append(
            disnake.ui.MediaGallery(disnake.MediaGalleryItem(REDUX_BANNER_URL))
        )

    children.append(
        disnake.ui.TextDisplay(
            f"## {e('REDUX')}Redux\n"
            f"{e('FAMILY')}Уникальный Redux — наша семейная разработка."
        )
    )
    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            f"{e('STYLE')}Gunpack для ценителей стиля и индивидуальности."
        )
    )
    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            f"{e('SHIELD_CHECK')}Redux прошёл проверку у чит-хантеров."
        )
    )
    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(
        disnake.ui.TextDisplay(
            "Если вдруг появятся баги — просто напишите, и мы быстро всё "
            "поправим и зальём фикс."
        )
    )
    children.append(
        disnake.ui.Separator(
            divider=True, spacing=disnake.SeparatorSpacing.small
        )
    )
    children.append(disnake.ui.TextDisplay("**Поехали:**"))

    select = disnake.ui.StringSelect(
        custom_id=REDUX_SELECT_CID,
        placeholder="Выбери, что хочешь открыть",
        min_values=1,
        max_values=1,
        options=[
            disnake.SelectOption(
                label="Spartan Redux",
                description="Установка и настройка редукса",
                value=REDUX_OPT_SPARTAN,
                emoji=e_btn("REDUX"),
            ),
            disnake.SelectOption(
                label="Gunpack",
                description="Скины оружия — 3 части",
                value=REDUX_OPT_GUNPACK,
                emoji=e_btn("GUN"),
            ),
            disnake.SelectOption(
                label="Sound",
                description="Звуковой пак",
                value=REDUX_OPT_SOUND,
                emoji=e_btn("SOUND"),
            ),
            disnake.SelectOption(
                label="Ошибка в redux или предложить идею",
                description="Открыть форму для отчёта/предложения",
                value=REDUX_OPT_BUG,
                emoji=e_btn("BUG"),
            ),
        ],
    )
    children.append(disnake.ui.ActionRow(select))

    return [
        disnake.ui.Container(
            *children, accent_colour=disnake.Colour(SKY_BLUE)
        )
    ]


# ==========================================
# ЭФЕМЕРНЫЕ ОТВЕТЫ ДЛЯ КАЖДОЙ ОПЦИИ
# ==========================================
def _spartan_redux_payload() -> tuple[list[disnake.Embed], disnake.ui.View]:
    desc = (
        f"{e('FILE')}На Google Диске вы найдёте и следующие файлы:\n"
        f"{e('POINT')}Основные файлы редукса — файл `update.rpf`\n\n"
        f"{e('DOWNLOAD')}Скачай архив с модом — обычно это `.zip` или `.rar`.\n\n"
        f"{e('UNZIP')}Распакуй файл `update.rpf` в корневую папку игры.\n\n"
        f"{e('STEAM')}**Стандартный путь Steam:**\n"
        f"`Steam\\steamapps\\common\\Grand Theft Auto V\\update`\n\n"
        f"{e('EPIC')}**Стандартный путь Epic:**\n"
        f"`Epic Games\\Grand Theft Auto V\\update`\n\n"
        f"{e('INFO')}В примере показаны стандартные пути установки "
        f"Grand Theft Auto V, которые используются, если не изменять "
        f"путь вручную при установке.\n\n"
        f"{e('RETICLE')}**Замена прицела.**\n"
        f"{e('RETICLE')}Хочешь поставить свой прицел? Открывай `update.rpf` "
        f"через OpenIV и просто замени файл тут:\n"
        f"`update.rpf\\component\\hud_reticle.rpf`\n\n"
        f"{e('WARNING')}Любое изменение редукса со сторонних ресурсов — "
        f"исключительно Ваша ответственность!"
    )

    embed = disnake.Embed(
        title=f"{e('REDUX')}Spartan Redux",
        description=desc,
        color=disnake.Colour(SKY_BLUE),
    )
    if SPARTAN_REDUX_IMAGE_URL:
        embed.set_image(url=SPARTAN_REDUX_IMAGE_URL)

    view = disnake.ui.View(timeout=None)
    view.add_item(
        disnake.ui.Button(
            label="Скачать update.rpf",
            style=disnake.ButtonStyle.link,
            url=SPARTAN_REDUX_DRIVE_URL,
            emoji=e_btn("FILE"),
        )
    )
    return [embed], view


def _gunpack_payload() -> tuple[list[disnake.Embed], disnake.ui.View]:
    embeds: list[disnake.Embed] = []
    view = disnake.ui.View(timeout=None)

    for idx, part in enumerate(GUNPACK_PARTS, start=1):
        embed = disnake.Embed(
            title=f"{e('GUN')}{part['title']}",
            color=disnake.Colour(SKY_BLUE),
        )
        if part.get("image"):
            embed.set_image(url=part["image"])
        embeds.append(embed)

        view.add_item(
            disnake.ui.Button(
                label=f"Скачать часть {idx}",
                style=disnake.ButtonStyle.link,
                url=part["drive"],
                emoji=e_btn("FILE"),
            )
        )

    return embeds, view


def _sound_payload() -> tuple[list[disnake.Embed], disnake.ui.View]:
    embed = disnake.Embed(
        title=f"{e('SOUND')}Sound",
        description=(
            f"{e('FILE')}Звуковой пак для редукса.\n"
            f"{e('DOWNLOAD')}Скачай архив по кнопке ниже и распакуй "
            f"в корневую папку игры так же, как и редукс."
        ),
        color=disnake.Colour(SKY_BLUE),
    )
    if SOUND_IMAGE_URL:
        embed.set_image(url=SOUND_IMAGE_URL)

    view = disnake.ui.View(timeout=None)
    view.add_item(
        disnake.ui.Button(
            label="Скачать Sound",
            style=disnake.ButtonStyle.link,
            url=SOUND_DRIVE_URL,
            emoji=e_btn("SOUND"),
        )
    )
    return [embed], view


# ==========================================
# МОДАЛКА: ОШИБКА / ИДЕЯ
# ==========================================
class BugReportModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Тип обращения",
                placeholder="Ошибка / Идея",
                custom_id="kind",
                style=disnake.TextInputStyle.short,
                max_length=50,
            ),
            disnake.ui.TextInput(
                label="Заголовок",
                placeholder="Кратко: о чём речь",
                custom_id="title",
                style=disnake.TextInputStyle.short,
                max_length=100,
            ),
            disnake.ui.TextInput(
                label="Описание",
                placeholder=(
                    "Опиши подробно: что происходит / что предлагаешь, "
                    "как воспроизвести и т.д."
                ),
                custom_id="description",
                style=disnake.TextInputStyle.paragraph,
                max_length=1500,
            ),
            disnake.ui.TextInput(
                label="Что использовалось (Spartan / Gunpack / Sound)",
                placeholder="Spartan Redux",
                custom_id="scope",
                style=disnake.TextInputStyle.short,
                required=False,
                max_length=100,
            ),
        ]
        super().__init__(
            title="Ошибка в redux / предложить идею",
            components=components,
            custom_id=REDUX_BUG_MODAL_CID,
        )

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)

        kind = inter.text_values.get("kind", "").strip() or "—"
        title = inter.text_values.get("title", "").strip() or "—"
        description = inter.text_values.get("description", "").strip() or "—"
        scope = inter.text_values.get("scope", "").strip() or "—"

        embed = disnake.Embed(
            title=f"{e('BUG')}Новое обращение по Redux",
            color=disnake.Colour.orange(),
        )
        embed.add_field(name="Тип", value=kind, inline=True)
        embed.add_field(name="Раздел", value=scope, inline=True)
        embed.add_field(
            name="Автор",
            value=f"{inter.author.mention} (`{inter.author.id}`)",
            inline=True,
        )
        embed.add_field(name="Заголовок", value=title, inline=False)
        embed.add_field(name="Описание", value=description, inline=False)

        if getattr(inter.author, "display_avatar", None):
            embed.set_thumbnail(url=inter.author.display_avatar.url)

        target_channel = None
        if BUG_REPORT_CHANNEL_ID:
            target_channel = inter.bot.get_channel(BUG_REPORT_CHANNEL_ID)
            if target_channel is None:
                try:
                    target_channel = await inter.bot.fetch_channel(
                        BUG_REPORT_CHANNEL_ID
                    )
                except Exception:
                    target_channel = None

        if target_channel is None:
            await inter.followup.send(
                f"{e('WARNING')}Не настроен канал для обращений "
                f"(`BUG_REPORT_CHANNEL_ID`). Сообщи администратору.",
                ephemeral=True,
            )
            return

        try:
            await target_channel.send(embed=embed)
        except Exception:
            await inter.followup.send(
                f"{e('WARNING')}Не удалось отправить обращение в канал. "
                f"Проверь права бота.",
                ephemeral=True,
            )
            return

        await inter.followup.send(
            f"{e('IDEA')}Спасибо! Твоё обращение отправлено.",
            ephemeral=True,
        )


# ==========================================
# COG
# ==========================================
class ReduxCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_dropdown(self, inter: disnake.MessageInteraction):
        if inter.component.custom_id != REDUX_SELECT_CID:
            return
        if not inter.values:
            return

        value = inter.values[0]

        if value == REDUX_OPT_SPARTAN:
            embeds, view = _spartan_redux_payload()
            await inter.response.send_message(
                embeds=embeds, view=view, ephemeral=True
            )
            return

        if value == REDUX_OPT_GUNPACK:
            embeds, view = _gunpack_payload()
            await inter.response.send_message(
                embeds=embeds, view=view, ephemeral=True
            )
            return

        if value == REDUX_OPT_SOUND:
            embeds, view = _sound_payload()
            await inter.response.send_message(
                embeds=embeds, view=view, ephemeral=True
            )
            return

        if value == REDUX_OPT_BUG:
            await inter.response.send_modal(BugReportModal())
            return

    @commands.command(name="redux")
    @commands.has_permissions(administrator=True)
    async def redux_panel(self, ctx: commands.Context):
        """Постит Components V2 панель Redux в текущий канал."""
        components = build_redux_panel()
        await ctx.send(components=components)
        try:
            await ctx.message.delete()
        except Exception:
            pass


def setup(bot):
    bot.add_cog(ReduxCog(bot))
