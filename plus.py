from __future__ import annotations

import asyncio
import json
import logging
import aiosqlite
import time
import re
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import disnake
from disnake.ext import commands, tasks

log = logging.getLogger("kraymore")

with open("config.json", "r", encoding="utf-8") as f:
    _cfg = json.load(f)

# ==========================================
# ПОМОЩНИКИ ДЛЯ ЭМОДЗИ И ЛОГО
# ==========================================
def e(key: str) -> str:
    """Для текста: возвращает эмодзи с пробелом или пустоту."""
    val = _cfg.get("EMOJIS", {}).get(key, "")
    return f"{val} " if val else ""

def e_btn(key: str):
    """Для кнопок/меню: возвращает эмодзи или None."""
    val = _cfg.get("EMOJIS", {}).get(key, "")
    return val if val else None

def get_safe_logo():
    logo = _cfg.get("IMAGES", {}).get("LOGO", "").strip()
    if logo.startswith("Https"):
        logo = logo.replace("Https", "https")
    return logo

# КАСТОМНЫЕ СМАЙЛИКИ МЕРОПРИЯТИЙ
EVENT_EMOJIS = {
    "CAPT": "<:capt:1490572831048597525>",
    "MCL": "<:mcl:1490572826959286282>",
    "ВЗЗ": "<:vzz:1490572829802893422>",
    "ВЗМ": "<:vzm:1490572828238549052>"
}
STATS_EMOJI = "<:skull_emoji:1490574119077412894>"

# КАСТОМНЫЕ СМАЙЛИКИ ТИРОВ (слева от участника в списке сбора)
# Подставь ID своих эмодзи на сервере: <:имя:ID>
TIER_EMOJIS = {
    1: "<:tier1:0000000000000000000>",       # S — Tier 1
    2: "<:tier2:0000000000000000000>",       # A — Tier 2
    3: "<:tier3:0000000000000000000>",       # B — Tier 3
    9: "<:tier_none:0000000000000000000>",   # — без тира
}
# Unicode-fallback на случай, если ID ещё не подставлены
TIER_EMOJI_FALLBACK = {1: "\U0001F7E1", 2: "\U0001F534", 3: "\U0001F535", 9: "\u2B1C"}

def _tier_emoji(tier_num: int) -> str:
    val = TIER_EMOJIS.get(tier_num, TIER_EMOJIS[9])
    # Если ID ещё дефолтный (нули) — отдадим Unicode-фолбэк
    if "0000000000000000000" in val:
        return TIER_EMOJI_FALLBACK.get(tier_num, TIER_EMOJI_FALLBACK[9])
    return val

# ==========================================

def get_safe_url(url: str) -> str:
    url = url.strip()
    if url.startswith("Https"):
        url = url.replace("Https", "https")
    return url

class PlusConfig:
    CAPT_STATS_CHANNEL_ID = _cfg["PLUS"]["STATS_CHANNEL"]
    PLUS_TIER1_ROLE_ID = _cfg["PLUS"]["TIER1_ROLE"]
    PLUS_TIER2_ROLE_ID = _cfg["PLUS"]["TIER2_ROLE"]
    PLUS_TIER3_ROLE_ID = _cfg["PLUS"]["TIER3_ROLE"]
    
    PLUS_SETTINGS_ROLE_IDS = _cfg["PLUS"]["SETTINGS_ROLES"]
    PLUS_PARTICIPANTS_MAX_LINES = 35  # Лимит отображаемых участников в эмбеде сбора
    PLUS_PARTICIPANTS_PAGE_SIZE = _cfg["PLUS"]["PARTICIPANTS_PAGE_SIZE"]
    PLUS_DM_MAX_RECIPIENTS = _cfg["PLUS"]["DM_MAX_RECIPIENTS"]
    
    CAPT_BANNER_URL = get_safe_url(_cfg.get("IMAGES", {}).get("PLUS_BANNER", ""))
    BAN_CAPT_ROLE_ID = _cfg["ROLES"]["BAN_CAPT"]

config = PlusConfig()

INVISIBLE_COLOR = 0x2b2d31
TZ_UTC3 = timezone(timedelta(hours=3))

# Глобальные блокировки для предотвращения конфликтов базы данных при быстрых нажатиях
_STATS_LOCK = asyncio.Lock()
_PLUS_ACTION_LOCK = asyncio.Lock()

def brand_embed(title: str, description: str, banner_url: str = "", color: int = INVISIBLE_COLOR) -> disnake.Embed:
    emb = disnake.Embed(title=title, description=description, color=color)
    if banner_url:
        try: emb.set_image(url=banner_url)
        except: pass
        
    logo = get_safe_logo()
    if logo:
        emb.set_footer(text="SPARTAN Famq", icon_url=logo)
    else:
        emb.set_footer(text="SPARTAN Famq")
        
    return emb

def _is_banned(user) -> bool:
    try:
        member = user.author if hasattr(user, "author") else user
        if isinstance(member, disnake.Member):
            return member.get_role(int(config.BAN_CAPT_ROLE_ID)) is not None
        return False
    except Exception:
        return False

# ==========================================
# ПАНЕЛЬ ЗАБЛОКИРОВАННЫХ (BAN CAPT)
# ==========================================
async def update_ban_panel(bot):
    async with aiosqlite.connect("data/database.sqlite") as db:
        async with db.execute("SELECT value FROM ban_config WHERE key = 'channel_id'") as cursor:
            c_row = await cursor.fetchone()
        async with db.execute("SELECT value FROM ban_config WHERE key = 'message_id'") as cursor:
            m_row = await cursor.fetchone()

        if not c_row or not m_row: return
        
        channel = bot.get_channel(int(c_row[0]))
        if not channel: return
        
        current_ts = int(time.time())
        # Снимаем баны с тех, у кого вышло время
        async with db.execute("SELECT user_id FROM banned_users WHERE expire_ts <= ?", (current_ts,)) as cursor:
            expired = await cursor.fetchall()
        
        for (uid,) in expired:
            guild = channel.guild
            member = guild.get_member(int(uid))
            if not member:
                try: member = await guild.fetch_member(int(uid))
                except: pass
            if member:
                role = guild.get_role(int(config.BAN_CAPT_ROLE_ID))
                if role:
                    try: await member.remove_roles(role, reason="Срок BAN CAPT истек")
                    except: pass
            await db.execute("DELETE FROM banned_users WHERE user_id = ?", (uid,))
        await db.commit()

        # Строим список текущих банов
        async with db.execute("SELECT user_id, admin_id, reason, expire_ts FROM banned_users ORDER BY expire_ts ASC") as cursor:
            bans = await cursor.fetchall()

    desc = ""
    if bans:
        for uid, aid, rsn, ets in bans:
            desc += f"👤 <@{uid}>\n└ **Спадёт:** <t:{ets}:R> | **Выдал:** <@{aid}>\n└ **Причина:** *{rsn}*\n\n"
    else:
        desc = "> *Список заблокированных пуст.*"

    embed = disnake.Embed(
        title="Список заблокированных - BAN CAPT",
        description=desc,
        color=INVISIBLE_COLOR,
        timestamp=datetime.now(timezone.utc)
    )
    logo = get_safe_logo()
    if logo:
        embed.set_footer(text="SPARTAN Famq • Авто-обновление каждую минуту", icon_url=logo)
    else:
        embed.set_footer(text="SPARTAN Famq • Авто-обновление каждую минуту")

    try:
        msg = await channel.fetch_message(int(m_row[0]))
        await msg.edit(embed=embed)
    except:
        pass

_STATS_PATH = Path("data/plus_stats.json")

def _stats_default() -> dict:
    return {
        "message_id": 0,
        "counts": {"CAPT": {"win": 0, "loss": 0}, "MCL": {"win": 0, "loss": 0}, "ВЗЗ": {"win": 0, "loss": 0}, "ВЗМ": {"win": 0, "loss": 0}},
        "updated_ts": 0,
    }

def _stats_load() -> dict:
    try:
        if _STATS_PATH.exists():
            with _STATS_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict): return _stats_default()
                data.setdefault("message_id", 0)
                data.setdefault("counts", {})
                for k in ("CAPT", "MCL", "ВЗЗ", "ВЗМ"):
                    v = data["counts"].get(k)
                    if isinstance(v, int): data["counts"][k] = {"win": int(v), "loss": 0}
                    elif isinstance(v, dict): v.setdefault("win", 0); v.setdefault("loss", 0)
                    else: data["counts"][k] = {"win": 0, "loss": 0}
                data.setdefault("updated_ts", 0)
                return data
    except Exception: pass
    return _stats_default()

def _stats_save(data: dict) -> None:
    try:
        _STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _STATS_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception: pass

def _build_stats_embed(data: dict) -> disnake.Embed:
    ts = int(data.get("updated_ts") or 0)
    counts = data.get("counts") or {}
    
    total_wins = 0
    total_losses = 0
    
    # Сначала считаем общие суммы
    for k, v in counts.items():
        if isinstance(v, int):
            total_wins += v
        elif isinstance(v, dict):
            total_wins += int(v.get("win", 0))
            total_losses += int(v.get("loss", 0))
            
    total_games = total_wins + total_losses
    
    # Формируем описание
    desc = f"Последнее обновление: <t:{ts}:R>" if ts else "—"
    desc += "\n\n**Детальная сводка:**"
    
    emb = brand_embed(
        title="Статистика PLUS", 
        description=desc, 
        banner_url=config.CAPT_BANNER_URL
    )
    
    # 1. ОБЩАЯ СТАТИСТИКА (с новой строки, чтобы не ломать сетку)
    emb.add_field(
        name=f"{STATS_EMOJI} Общая статистика", 
        value=f"> Сыграно: **{total_games}**\n> Побед: **{total_wins}**\n> Поражений: **{total_losses}**", 
        inline=False
    )
    
    # 2. СТАТИСТИКА ПО КАЖДОМУ МЕРОПРИЯТИЮ (В РЯД, ИДЕАЛЬНАЯ СЕТКА)
    count_idx = 0
    for k, v in counts.items():
        type_wins = 0
        type_losses = 0
        if isinstance(v, int):
            type_wins = v
        elif isinstance(v, dict):
            type_wins = int(v.get("win", 0))
            type_losses = int(v.get("loss", 0))
            
        type_total = type_wins + type_losses
        
        # Берем кастомный эмодзи или используем дефолтный 📍
        ev_emoji = EVENT_EMOJIS.get(k, "📍")
        
        emb.add_field(
            name=f"{ev_emoji} {k}",
            value=f"> Сыграно: **{type_total}**\n> Побед: **{type_wins}**\n> Поражений: **{type_losses}**",
            inline=True
        )
        
        count_idx += 1
        # Вставляем пустой блок каждые 2 элемента, чтобы выровнять всё в идеальную сетку 2x2
        if count_idx % 2 == 0:
            emb.add_field(name="\u200b", value="\u200b", inline=True)
    
    logo = get_safe_logo()
    if logo:
        emb.set_footer(text="SPARTAN Famq • Авто-обновление каждую минуту", icon_url=logo)
    else:
        emb.set_footer(text="SPARTAN Famq • Авто-обновление каждую минуту")
        
    return emb

async def _update_or_send_stats(bot, channel, embed, data):
    found_msgs = []
    try:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and msg.embeds and "Статистика PLUS" in str(msg.embeds[0].title):
                found_msgs.append(msg)
    except Exception:
        pass

    bot_msg = None
    if found_msgs:
        bot_msg = found_msgs[0]
        data["message_id"] = bot_msg.id
        
        for m in found_msgs[1:]:
            try: await m.delete()
            except Exception: pass

    if bot_msg:
        try: await bot_msg.edit(embed=embed)
        except Exception: pass
    else:
        try:
            new_msg = await channel.send(embed=embed)
            data["message_id"] = new_msg.id
        except Exception: pass

    _stats_save(data)

def _has_settings_access(member: disnake.Member) -> bool:
    try: return any(r.id in set(config.PLUS_SETTINGS_ROLE_IDS) for r in member.roles)
    except Exception: return False

def _tier_number_from_member(member: disnake.Member) -> tuple[int, str]:
    role_ids = {r.id for r in member.roles}
    if config.PLUS_TIER1_ROLE_ID in role_ids: return 1, "Tier 1"
    if config.PLUS_TIER2_ROLE_ID in role_ids: return 2, "Tier 2"
    if config.PLUS_TIER3_ROLE_ID in role_ids: return 3, "Tier 3"
    return 9, "Tier —"

@dataclass
class PlusState:
    event_type: str
    ts: int
    base_slots: int
    extra_slots: int
    closed: bool = False
    image_url: str = ""
    thumbnail_url: str = ""
    logs_enabled: bool = False
    logs_thread_id: int = 0
    revealed: bool = False
    warned: bool = False  
    members: list[int] = field(default_factory=list)
    pending_members: list[int] = field(default_factory=list)
    ping_message_id: int = 0

    @property
    def total_slots(self) -> int: return self.base_slots + self.extra_slots
    @property
    def used(self) -> int: return len(self.members)
    @property
    def is_full(self) -> bool: return self.used >= self.total_slots

async def save_plus_state(message_id: int, channel_id: int, state: PlusState):
    async with aiosqlite.connect("data/database.sqlite") as db:
        await db.execute(
            "INSERT OR REPLACE INTO active_plus_events (message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_members, ping_message_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(message_id), str(channel_id), state.event_type, state.ts, state.base_slots, state.extra_slots, int(state.closed), json.dumps(state.members), int(state.revealed), int(state.warned), int(state.logs_enabled), str(state.logs_thread_id), state.image_url, json.dumps(state.pending_members), str(state.ping_message_id))
        )
        await db.commit()

async def delete_plus_state(message_id: int):
    async with aiosqlite.connect("data/database.sqlite") as db:
        await db.execute("DELETE FROM active_plus_events WHERE message_id = ?", (str(message_id),))
        await db.commit()

class PlusEventView(disnake.ui.View):
    def __init__(self, bot: commands.InteractionBot, state: PlusState):
        super().__init__(timeout=None)
        self.bot = bot
        self.state = state
        self.message: Optional[disnake.Message] = None
        self._tier_cache: dict[int, tuple[int, str]] = {}
        
        current_ts = datetime.now(timezone.utc).timestamp()
        
        # Кнопки Join/Leave всегда доступны и не зависят от времени сбора
        join_btn = disnake.ui.Button(label="Присоединиться", style=disnake.ButtonStyle.success, custom_id="plus_join", emoji=e_btn("JOIN"), row=0)
        join_btn.callback = self.join_callback
        self.add_item(join_btn)

        leave_btn = disnake.ui.Button(label="Покинуть", style=disnake.ButtonStyle.danger, custom_id="plus_leave", emoji=e_btn("LEAVE"), row=0)
        leave_btn.callback = self.leave_callback
        self.add_item(leave_btn)

        options = []
        if current_ts < self.state.ts and not self.state.revealed:
            options.append(disnake.SelectOption(label="Список", description="Посмотреть полный список участников", value="list", emoji=e_btn("LIST")))
            options.append(disnake.SelectOption(label="Меню", description="Управление сбором (Только для Админов)", value="settings", emoji=e_btn("SETTINGS")))
        else:
            options.append(disnake.SelectOption(label="Список", description="Посмотреть полный список участников", value="list", emoji=e_btn("LIST")))
            options.append(disnake.SelectOption(label="Победа", description="Завершить сбор победой", value="win", emoji=e_btn("WIN")))
            options.append(disnake.SelectOption(label="Поражение", description="Завершить сбор поражением", value="loss", emoji=e_btn("LOSS")))

        self.select = disnake.ui.StringSelect(placeholder="Дополнительные действия...", custom_id="plus_action_select", options=options, row=1)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if _is_banned(inter):
            await inter.response.send_message(f"{e('REJECT')}Вы заблокированы и не можете взаимодействовать со сборами PLUS.", ephemeral=True)
            return False
        return True

    async def join_callback(self, inter: disnake.MessageInteraction):
        # Моментально отвечаем дискорду, чтобы не было лагов и ошибок "Взаимодействие не удалось"
        await inter.response.defer(ephemeral=True)
        self.message = inter.message
                
        if self.state.closed: 
            return await inter.followup.send(f"{e('REJECT')}Сбор закрыт.", ephemeral=True)
        if inter.user.id in self.state.members: 
            return await inter.followup.send(f"{e('WARNING')}Ты уже в списке участников.", ephemeral=True)
        if inter.user.id in self.state.pending_members: 
            return await inter.followup.send(f"{e('WARNING')}Ты уже подал заявку. Ожидай решения модератора.", ephemeral=True)
        if self.state.is_full: 
            return await inter.followup.send(f"{e('ERROR')}Слоты закончились.", ephemeral=True)
        
        self.state.pending_members.append(inter.user.id)
        await save_plus_state(inter.message.id, inter.channel.id, self.state)

        if self.state.logs_thread_id:
            thread = inter.guild.get_thread(self.state.logs_thread_id)
            if thread:
                # Удаляем старые заявки этого пользователя из ветки (оптимизировано до 50 сообщений для скорости)
                async for m in thread.history(limit=50):
                    if m.author.id == self.bot.user.id and inter.user in m.mentions:
                        try:
                            await m.delete()
                        except Exception: pass
                        
                _, tier_label = await self._get_tier(inter.guild, inter.user.id)
                await thread.send(f"{e('JOIN')} {inter.user.mention} (**{tier_label}**) подал заявку на участие в сборе!")
                return await inter.followup.send(f"{e('SUCCESS')}Твоя заявка отправлена в ветку сбора! Ожидай подтверждения от проверяющих.", ephemeral=True)
        
        await inter.followup.send(f"{e('ERROR')}Ошибка: ветка сбора не найдена.", ephemeral=True)

    async def leave_callback(self, inter: disnake.MessageInteraction):
        # Моментально отвечаем дискорду
        await inter.response.defer(ephemeral=True)
        self.message = inter.message
        
        in_members = inter.user.id in self.state.members
        in_pending = inter.user.id in self.state.pending_members
        
        if not in_members and not in_pending: 
            return await inter.followup.send(f"{e('WARNING')}Тебя нет в списках.", ephemeral=True)
        
        if in_members:
            self.state.members.remove(inter.user.id)
            self._tier_cache.pop(inter.user.id, None)
        if in_pending:
            self.state.pending_members.remove(inter.user.id)
            
        await save_plus_state(inter.message.id, inter.channel.id, self.state)
        
        await inter.followup.send(f"{e('SUCCESS')}Вы отменили свою заявку на сбор.", ephemeral=True)
        await self.refresh_message(inter.guild)
        
        if self.state.logs_thread_id:
            thread = inter.guild.get_thread(self.state.logs_thread_id)
            if thread:
                # Оптимизировано: проверяем только последние 50 сообщений вместо 100
                async for m in thread.history(limit=50):
                    if m.author.id == inter.user.id or (m.author.id == self.bot.user.id and inter.user in m.mentions):
                        try: await m.clear_reaction("✅")
                        except Exception: pass
                        try: await m.add_reaction("🔴")
                        except Exception: pass
                        break

    async def select_callback(self, inter: disnake.MessageInteraction):
        self.message = inter.message
        action = self.select.values[0]
        
        if action == "list":
            await self.handle_list(inter)
        elif action == "settings":
            await self.handle_settings(inter)
        elif action == "win":
            await self.handle_win(inter)
        elif action == "loss":
            await self.handle_loss(inter)

    async def _get_tier(self, guild: disnake.Guild, user_id: int) -> tuple[int, str]:
        if user_id in self._tier_cache: return self._tier_cache[user_id]
        
        member = guild.get_member(user_id)
        if not member:
            try: member = await guild.fetch_member(user_id)
            except Exception: member = None
                
        res = _tier_number_from_member(member) if member else (9, "Tier —")
        self._tier_cache[user_id] = res
        return res

    async def _participants_text(self, guild: disnake.Guild) -> str:
        if not self.state.members: return "> —"
        lines = await self._participants_lines(guild)
        if len(lines) > config.PLUS_PARTICIPANTS_MAX_LINES:
            rest = len(lines) - config.PLUS_PARTICIPANTS_MAX_LINES
            lines = lines[:config.PLUS_PARTICIPANTS_MAX_LINES]
            lines.append(f"> … + ещё {rest} участн.")
        return "\n".join(lines)

    async def _participants_chunks(self, guild: disnake.Guild, *, field_max: int = 1024) -> list[str]:
        """Возвращает список участников, разбитый на чанки <= field_max символов
        (Discord embed field value limit), чтобы 35 строк гарантированно помещались
        даже с длинными кастомными эмодзи и mention-ами."""
        if not self.state.members:
            return []
        lines = await self._participants_lines(guild)
        if len(lines) > config.PLUS_PARTICIPANTS_MAX_LINES:
            rest = len(lines) - config.PLUS_PARTICIPANTS_MAX_LINES
            lines = lines[:config.PLUS_PARTICIPANTS_MAX_LINES]
            lines.append(f"> … + ещё {rest} участн.")

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for line in lines:
            extra = len(line) + (1 if current else 0)  # +1 для \n
            if current and current_len + extra > field_max:
                chunks.append("\n".join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += extra
        if current:
            chunks.append("\n".join(current))
        return chunks

    async def _participants_lines(self, guild: disnake.Guild) -> list[str]:
        if not self.state.members: return []
        enriched = []
        for idx, uid in enumerate(self.state.members):
            tier_num, tier_label = await self._get_tier(guild, uid)
            enriched.append((tier_num, idx, uid, tier_label))
        enriched.sort(key=lambda x: (x[0], x[1]))
        return [f"> `{i:02d}.` {_tier_emoji(tier_num)} <@{uid}>" for i, (tier_num, _, uid, _) in enumerate(enriched, start=1)]

    async def build_embed(self, guild: disnake.Guild) -> disnake.Embed:
        current_ts = datetime.now(timezone.utc).timestamp()
        
        if self.state.closed: status = f"{e('CLOSED')}**СБОР ЗАКРЫТ**"
        elif self.state.revealed or current_ts >= self.state.ts:
            status = f"{e('TIMER')}**СБОР ОКОНЧЕН (Ожидание итогов)**"
        elif self.state.is_full: status = f"{e('FULL')}**СЛОТЫ ЗАПОЛНЕНЫ**"
        else: status = f"{e('OPEN')}**СБОР ОТКРЫТ**"
        
        desc = f"{status} {e('TIME')}<t:{self.state.ts}:F> (<t:{self.state.ts}:R>)"
        
        # Получаем кастомный эмодзи для заголовка
        ev_emoji = EVENT_EMOJIS.get(self.state.event_type, e('PLUS'))
        emb = brand_embed(title=f"{ev_emoji} PLUS | {self.state.event_type}", description=desc)

        # Список участников — с учётом лимита Discord 1024 симв./поле,
        # длинный список бьём на несколько полей, чтобы все 35 строк помещались.
        participants_field_name = f"Участники: {e('PEOPLE')}{self.state.used}/{self.state.total_slots}"
        chunks = await self._participants_chunks(guild)
        if not chunks:
            emb.add_field(name=participants_field_name, value="> —", inline=False)
        else:
            emb.add_field(name=participants_field_name, value=chunks[0], inline=False)
            for extra in chunks[1:]:
                emb.add_field(name="\u200b", value=extra, inline=False)
        
        if self.state.logs_enabled and self.state.logs_thread_id: 
            emb.add_field(name=f"{e('RECEIPT')}Ветка сбора", value=f"<#{self.state.logs_thread_id}>", inline=False)
        if self.state.thumbnail_url: emb.set_thumbnail(url=self.state.thumbnail_url)
        if self.state.image_url: emb.set_image(url=self.state.image_url)
        return emb

    async def refresh_message(self, guild: disnake.Guild):
        if not self.message: return
        for child in self.children:
            if getattr(child, "custom_id", "") == "plus_join":
                child.disabled = self.state.closed or self.state.is_full
            if getattr(child, "custom_id", "") == "plus_leave":
                child.disabled = self.state.closed

        try: 
            embed = await self.build_embed(guild)
            await self.message.edit(embed=embed, view=self)
        except disnake.HTTPException: 
            pass

    async def _ensure_logs_thread(self) -> Optional[disnake.Thread]:
        if not self.state.logs_enabled or not self.message: return None
        if self.state.logs_thread_id:
            ch = self.bot.get_channel(int(self.state.logs_thread_id))
            if isinstance(ch, disnake.Thread): return ch
        return None

    async def log_to_thread(self, text: str):
        if thread := await self._ensure_logs_thread():
            try: await thread.send(text)
            except disnake.HTTPException: pass

    async def ping_main_role(self, channel: disnake.abc.Messageable) -> int:
        roles_to_ping = [1183854185586901063, 1183863207576739931, 1322890140913369178]
        mentions = " ".join([f"<@&{r_id}>" for r_id in roles_to_ping])
        try: 
            ping_msg = await channel.send(f"{mentions} - плюса на {self.state.event_type}")
            self.state.ping_message_id = ping_msg.id
            return ping_msg.id
        except disnake.HTTPException: 
            return 0

    async def delete_role_ping(self):
        if not self.state.ping_message_id or not self.message:
            return
        try:
            channel = self.message.channel
            ping_msg = await channel.fetch_message(int(self.state.ping_message_id))
            await ping_msg.delete()
        except Exception:
            pass
        self.state.ping_message_id = 0

    async def notify_participants_dm(self, guild: disnake.Guild, actor_id: int):
        target_members = set()
        
        # Перебираем только тех, кто находится в списке участников сбора
        for uid in self.state.members:
            member = guild.get_member(uid)
            if not member:
                try:
                    member = await guild.fetch_member(uid)
                except Exception:
                    continue
                    
            if member and not member.bot:
                target_members.add(member)
                
        if not target_members:
            await self.log_to_thread(f"{e('ERROR')}Не удалось найти участников для рассылки.")
            return
        
        ev_emoji = EVENT_EMOJIS.get(self.state.event_type, e('PLUS'))
        embed = disnake.Embed(
            title=f"{e('PING')}Внимание участникам сбора!",
            description=f"Организатор вызывает участников сбора на **{ev_emoji} {self.state.event_type}**!\n\n{e('TIME')}**Начало:** <t:{self.state.ts}:F> (<t:{self.state.ts}:R>)\n\n[🔗 Перейдите в канал со сбором]({self.message.jump_url if self.message else '#'})",
            color=disnake.Color.blue()
        )
        
        logo = get_safe_logo()
        if logo:
            embed.set_footer(text="SPARTAN Famq", icon_url=logo)
        else:
            embed.set_footer(text="SPARTAN Famq")
        
        success = 0
        for member in target_members:
            try:
                await member.send(embed=embed)
                success += 1
                await asyncio.sleep(0.1) 
            except disnake.HTTPException:
                pass
                
        await self.log_to_thread(f"{e('PING')}Рассылка в ЛС участникам завершена. Успешно: {success} чел. (админ: <@{actor_id}>)")

    async def notify_5_min_warning(self):
        if not self.state.members: return
        
        ev_emoji = EVENT_EMOJIS.get(self.state.event_type, e('PLUS'))
        embed = disnake.Embed(
            title=f"{e('ALARM')}Скоро начало!",
            description=f"Мероприятие **{ev_emoji} PLUS | {self.state.event_type}** начнется менее чем через 5 минут!\n\nПожалуйста, заходите в игру и будьте готовы!\n\n[🔗 Перейти к сбору]({self.message.jump_url if self.message else '#'})",
            color=disnake.Color.orange()
        )
        
        logo = get_safe_logo()
        if logo:
            embed.set_footer(text="SPARTAN Famq", icon_url=logo)
        else:
            embed.set_footer(text="SPARTAN Famq")
        
        for uid in self.state.members:
            user = self.bot.get_user(uid) or await self.bot.fetch_user(uid)
            if user:
                try:
                    await user.send(embed=embed)
                    await asyncio.sleep(0.1) 
                except disnake.HTTPException:
                    pass
                    
        await self.log_to_thread(f"{e('ALARM')}Авто-уведомление за 5 минут успешно разослано участникам.")

    async def finish_plus(self, *, actor_id: int, result: str) -> tuple[bool, str]:
        if result not in ("win", "loss"): return False, "Неверный результат."
        
        stats_channel_id = int(config.CAPT_STATS_CHANNEL_ID)
        if stats_channel_id != 0:
            stats_channel = self.bot.get_channel(stats_channel_id)
            if isinstance(stats_channel, disnake.TextChannel):
                async with _STATS_LOCK:
                    data = _stats_load()
                    counts = data.get("counts") or {}
                    for k in ("CAPT", "MCL", "ВЗЗ", "ВЗМ"):
                        if isinstance(counts.get(k), int): counts[k] = {"win": int(counts[k]), "loss": 0}
                        elif isinstance(counts.get(k), dict): counts[k].setdefault("win", 0); counts[k].setdefault("loss", 0)
                        else: counts[k] = {"win": 0, "loss": 0}
                    
                    if self.state.event_type in counts:
                        counts[self.state.event_type][result] += 1
                        
                    data["counts"], data["updated_ts"] = counts, int(datetime.now(timezone.utc).timestamp())
                    emb = _build_stats_embed(data)
                    
                    await _update_or_send_stats(self.bot, stats_channel, emb, data)
            
        res_text = "ПОБЕДА" if result == "win" else "ПОРАЖЕНИЕ"
        await self.log_to_thread(f"{e('FINISH')}PLUS завершён ({res_text}): тип={self.state.event_type}, участников={self.state.used}/{self.state.total_slots} (админ: <@{actor_id}>)")
        
        self.state.closed = True
        
        # Удаляем пинг ролей перед удалением эмбеда
        await self.delete_role_ping()
        
        if self.message:
            await delete_plus_state(self.message.id)
            try:
                await self.message.delete()
                return True, "Сбор успешно завершён."
            except Exception:
                for item in self.children:
                    if getattr(item, "custom_id", "") in ["plus_join", "plus_leave"]:
                        item.disabled = True
                    if getattr(item, "custom_id", "") == "plus_action_select":
                        item.disabled = True
                try: await self.message.edit(view=self)
                except Exception: pass
                return True, "Сбор завершён: меню заблокировано."
        return True, "Сбор завершён."

    async def handle_settings(self, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
        await inter.response.send_message("Управление сбором:", ephemeral=True, view=PlusSettingsView(self))

    async def handle_list(self, inter: disnake.MessageInteraction):
        # Моментально отвечаем дискорду
        await inter.response.defer(ephemeral=True)
        if not inter.guild: return await inter.followup.send("Только на сервере.", ephemeral=True)
        lines = await self._participants_lines(inter.guild)
        if not lines: return await inter.followup.send("Список пуст.", ephemeral=True)
        view = ParticipantListView(self, page=0)
        view._update_buttons(len(lines))
        await inter.followup.send(embed=await view.build_page_embed(inter.guild), view=view, ephemeral=True)

    async def handle_win(self, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user):
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        ok, msg = await self.finish_plus(actor_id=inter.user.id, result="win")
        await inter.followup.send(msg, ephemeral=True)

    async def handle_loss(self, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user):
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
        await inter.response.defer(ephemeral=True)
        ok, msg = await self.finish_plus(actor_id=inter.user.id, result="loss")
        await inter.followup.send(msg, ephemeral=True)


class ParticipantListView(disnake.ui.View):
    def __init__(self, parent: PlusEventView, page: int = 0):
        super().__init__(timeout=180)
        self.parent = parent
        self.page = max(0, int(page))

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if _is_banned(inter):
            await inter.response.send_message(f"{e('REJECT')}Вы заблокированы.", ephemeral=True)
            return False
        return True

    async def build_page_embed(self, guild: disnake.Guild) -> disnake.Embed:
        lines = await self.parent._participants_lines(guild)
        total = len(lines)
        if total == 0: desc, pages, self.page, chunk = "> Список пуст.", 1, 0, []
        else:
            pages = max(1, (total + config.PLUS_PARTICIPANTS_PAGE_SIZE - 1) // config.PLUS_PARTICIPANTS_PAGE_SIZE)
            self.page = min(self.page, pages - 1)
            chunk = lines[self.page * config.PLUS_PARTICIPANTS_PAGE_SIZE:(self.page + 1) * config.PLUS_PARTICIPANTS_PAGE_SIZE]
            desc = f"**Тип:** `{self.parent.state.event_type}`\n**Слоты:** `{self.parent.state.used} / {self.parent.state.total_slots}`\n**Страница:** `{self.page + 1} / {pages}`"
        emb = brand_embed(title=f"{e('LIST')}Список участников", description=desc)
        if chunk: emb.add_field(name="Участники", value="\n".join(chunk), inline=False)
        return emb
        
    def _update_buttons(self, total: int):
        pages = max(1, (total + config.PLUS_PARTICIPANTS_PAGE_SIZE - 1) // config.PLUS_PARTICIPANTS_PAGE_SIZE)
        self.prev_btn.disabled = self.page <= 0
        self.next_btn.disabled = self.page >= pages - 1
        
    async def _refresh(self, inter: disnake.MessageInteraction):
        if not inter.guild: return
        self._update_buttons(len(await self.parent._participants_lines(inter.guild)))
        await inter.response.edit_message(embed=await self.build_page_embed(inter.guild), view=self)
        
    @disnake.ui.button(label="Назад", style=disnake.ButtonStyle.secondary, emoji=e_btn("PREV"))
    async def prev_btn(self, button, inter): 
        self.page = max(0, self.page - 1); await self._refresh(inter)
        
    @disnake.ui.button(label="Вперед", style=disnake.ButtonStyle.secondary, emoji=e_btn("NEXT"))
    async def next_btn(self, button, inter): 
        self.page += 1; await self._refresh(inter)
        
    @disnake.ui.button(label="Закрыть", style=disnake.ButtonStyle.danger, emoji=e_btn("REJECT"))
    async def close_btn(self, button, inter): 
        await inter.response.edit_message(view=None)


class PlusSettingsView(disnake.ui.View):
    def __init__(self, event_view: PlusEventView):
        super().__init__(timeout=5 * 60)
        self.event_view = event_view

    @disnake.ui.button(label="Затянуть в Voice", style=disnake.ButtonStyle.primary, row=0, emoji=e_btn("VOICE"))
    async def pull_to_voice_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
            
        if not inter.user.voice or not inter.user.voice.channel:
            return await inter.response.send_message(f"{e('ERROR')}Ошибка: Вы должны находиться в голосовом канале, чтобы затянуть туда участников!", ephemeral=True)

        ev = self.event_view
        ev.message = ev.message or inter.message
        target_channel = inter.user.voice.channel

        await inter.response.defer(ephemeral=True)

        moved = 0
        for uid in ev.state.members:
            member = inter.guild.get_member(uid)
            if member and member.voice and member.voice.channel:
                if member.voice.channel.id != target_channel.id:
                    try:
                        await member.move_to(target_channel)
                        moved += 1
                        await asyncio.sleep(0.2) 
                    except:
                        pass

        await inter.followup.send(f"{e('SUCCESS')}Успешно затянуто **{moved}** участников в канал `{target_channel.name}`!", ephemeral=True)
        await ev.log_to_thread(f"{e('VOICE')}Админ <@{inter.user.id}> массово затянул {moved} участников в голосовой канал {target_channel.name}.")
        
    @disnake.ui.button(label="Оповестить в ЛС", style=disnake.ButtonStyle.primary, row=0, emoji=e_btn("DM"))
    async def notify_main_ls_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
            
        ev = self.event_view
        ev.message = ev.message or inter.message
        
        # Проверяем, есть ли вообще участники в списке
        if not ev.state.members:
            return await inter.response.send_message(f"{e('WARNING')}В списке нет участников для рассылки.", ephemeral=True)
        
        await inter.response.send_message("Начинаю рассылку в ЛС участникам... Это может занять несколько секунд.", ephemeral=True)
        await ev.notify_participants_dm(inter.guild, inter.user.id)

    @disnake.ui.button(label="Принудительно закрыть", style=disnake.ButtonStyle.danger, row=0, emoji=e_btn("LOCK"))
    async def force_close_btn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not isinstance(inter.user, disnake.Member) or not _has_settings_access(inter.user): 
            return await inter.response.send_message(f"{e('REJECT')}Нет доступа.", ephemeral=True)
            
        ev = self.event_view
        ev.message = ev.message or inter.message
        
        if ev.state.closed or ev.state.revealed:
            return await inter.response.send_message(f"{e('WARNING')}Сбор уже закрыт или время уже вышло!", ephemeral=True)
            
        await inter.response.defer(ephemeral=True)
        
        ev.state.revealed = True
        ev.state.warned = True 
        
        new_view = PlusEventView(ev.bot, ev.state)
        new_view.message = ev.message
        
        embed = await new_view.build_embed(inter.guild)
        await ev.message.edit(embed=embed, view=new_view)
        
        await save_plus_state(ev.message.id, ev.message.channel.id, ev.state)
        await ev.log_to_thread(f"{e('LOCK')}Админ <@{inter.user.id}> принудительно закрыл сбор раньше времени.")
        
        for child in self.children:
            child.disabled = True
        await inter.edit_original_response(view=self)
        
        await inter.followup.send(f"{e('SUCCESS')}Сбор принудительно закрыт. Меню обновлено.", ephemeral=True)


class PlusCog(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS active_plus_events (
                message_id TEXT PRIMARY KEY,
                channel_id TEXT,
                event_type TEXT,
                ts INTEGER,
                base_slots INTEGER,
                extra_slots INTEGER,
                closed INTEGER,
                members TEXT,
                revealed INTEGER DEFAULT 0,
                warned INTEGER DEFAULT 0,
                logs_enabled INTEGER DEFAULT 0,
                logs_thread_id TEXT DEFAULT '0',
                image_url TEXT DEFAULT '',
                pending_members TEXT DEFAULT '[]',
                ping_message_id TEXT DEFAULT '0'
            )""")
            
            # ТАБЛИЦЫ ДЛЯ BAN CAPT
            await db.execute("CREATE TABLE IF NOT EXISTS banned_users (user_id TEXT PRIMARY KEY, admin_id TEXT, reason TEXT, expire_ts INTEGER)")
            await db.execute("CREATE TABLE IF NOT EXISTS ban_config (key TEXT PRIMARY KEY, value TEXT)")
            
            try: await db.execute("ALTER TABLE active_plus_events ADD COLUMN revealed INTEGER DEFAULT 0")
            except Exception: pass
            try: await db.execute("ALTER TABLE active_plus_events ADD COLUMN warned INTEGER DEFAULT 0")
            except Exception: pass
            try: await db.execute("ALTER TABLE active_plus_events ADD COLUMN logs_enabled INTEGER DEFAULT 0")
            except Exception: pass
            try: await db.execute("ALTER TABLE active_plus_events ADD COLUMN logs_thread_id TEXT DEFAULT '0'")
            except Exception: pass
            try: await db.execute("ALTER TABLE active_plus_events ADD COLUMN image_url TEXT DEFAULT ''")
            except Exception: pass
            try: await db.execute("ALTER TABLE active_plus_events ADD COLUMN pending_members TEXT DEFAULT '[]'")
            except Exception: pass
            try: await db.execute("ALTER TABLE active_plus_events ADD COLUMN ping_message_id TEXT DEFAULT '0'")
            except Exception: pass
            await db.commit()
            
            async with db.execute("SELECT message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_members, ping_message_id FROM active_plus_events") as cursor:
                rows = await cursor.fetchall()
                
            for row in rows:
                message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members_json, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_json, ping_message_id = row
                try: members = json.loads(members_json)
                except: members = []
                try: pending_members = json.loads(pending_json)
                except: pending_members = []
                
                state = PlusState(
                    event_type=event_type, ts=ts, base_slots=base_slots, extra_slots=extra_slots,
                    closed=bool(closed), members=members, revealed=bool(revealed), warned=bool(warned),
                    logs_enabled=bool(logs_enabled), logs_thread_id=int(logs_thread_id), image_url=image_url or "", pending_members=pending_members,
                    ping_message_id=int(ping_message_id or 0)
                )
                
                view = PlusEventView(self.bot, state)
                self.bot.add_view(view, message_id=int(message_id))

        if not self.auto_update_loop.is_running():
            self.auto_update_loop.start()
            
    # ==========================================
    # ЛОГИКА ДОБАВЛЕНИЯ ЧЕРЕЗ ГАЛОЧКУ ✅ (С АНТИ-СПАМОМ)
    # ==========================================
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: disnake.RawReactionActionEvent):
        if str(payload.emoji.name) != "✅":
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        
        member = guild.get_member(payload.user_id)
        if not member or member.bot: return
        
        if not _has_settings_access(member): return

        # Блокировка от конфликтов базы данных
        async with _PLUS_ACTION_LOCK:
            async with aiosqlite.connect("data/database.sqlite") as db:
                async with db.execute("SELECT message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_members, ping_message_id FROM active_plus_events WHERE logs_thread_id = ?", (str(payload.channel_id),)) as cursor:
                    row = await cursor.fetchone()
                    
            if not row: return
            
            message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members_json, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_json, ping_message_id = row
            
            if closed or revealed: return
            
            try: members = json.loads(members_json)
            except: members = []
            try: pending_members = json.loads(pending_json)
            except: pending_members = []
            
            channel = guild.get_thread(payload.channel_id) or guild.get_channel(payload.channel_id)
            if not channel: return
            
            try: msg = await channel.fetch_message(payload.message_id)
            except: return
                
            target_user = None
            if msg.author.id == self.bot.user.id:
                if msg.mentions:
                    target_user = msg.mentions[0]
            elif msg.author.id == member.id:
                if msg.mentions:
                    target_user = msg.mentions[0]
                else:
                    return

            if not target_user or target_user.bot: return
            if _is_banned(target_user): return
            if target_user.id in members: return
                
            total_slots = base_slots + extra_slots
            if len(members) >= total_slots: return
                
            members.append(target_user.id)
            
            state = PlusState(
                event_type=event_type, ts=ts, base_slots=base_slots, extra_slots=extra_slots,
                closed=bool(closed), members=members, revealed=bool(revealed), warned=bool(warned),
                logs_enabled=bool(logs_enabled), logs_thread_id=int(logs_thread_id), image_url=image_url or "", pending_members=pending_members,
                ping_message_id=int(ping_message_id or 0)
            )
            
            await save_plus_state(message_id, channel_id, state)
            
            main_channel = guild.get_channel(int(channel_id))
            if main_channel:
                try:
                    main_msg = await main_channel.fetch_message(int(message_id))
                    view = PlusEventView(self.bot, state)
                    view.message = main_msg
                    embed = await view.build_embed(guild)
                    await main_msg.edit(embed=embed, view=view)
                except Exception: pass

    # ==========================================
    # ЛОГИКА УДАЛЕНИЯ ПРИ СНЯТИИ ГАЛОЧКИ ✅ (С АНТИ-СПАМОМ)
    # ==========================================
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: disnake.RawReactionActionEvent):
        if str(payload.emoji.name) != "✅":
            return
            
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        
        member = guild.get_member(payload.user_id)
        if not member or member.bot: return
        
        if not _has_settings_access(member): return

        # Блокировка от конфликтов базы данных
        async with _PLUS_ACTION_LOCK:
            async with aiosqlite.connect("data/database.sqlite") as db:
                async with db.execute("SELECT message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_members, ping_message_id FROM active_plus_events WHERE logs_thread_id = ?", (str(payload.channel_id),)) as cursor:
                    row = await cursor.fetchone()
                    
            if not row: return
            
            message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members_json, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_json, ping_message_id = row
            
            if closed or revealed: return
            
            try: members = json.loads(members_json)
            except: members = []
            try: pending_members = json.loads(pending_json)
            except: pending_members = []
            
            channel = guild.get_thread(payload.channel_id) or guild.get_channel(payload.channel_id)
            if not channel: return
            
            try: msg = await channel.fetch_message(payload.message_id)
            except: return
                
            target_user = None
            if msg.author.id == self.bot.user.id:
                if msg.mentions:
                    target_user = msg.mentions[0]
            elif msg.author.id == member.id:
                if msg.mentions:
                    target_user = msg.mentions[0]
                else:
                    return

            if not target_user or target_user.bot: return
            if target_user.id not in members: return
                
            members.remove(target_user.id)
            
            state = PlusState(
                event_type=event_type, ts=ts, base_slots=base_slots, extra_slots=extra_slots,
                closed=bool(closed), members=members, revealed=bool(revealed), warned=bool(warned),
                logs_enabled=bool(logs_enabled), logs_thread_id=int(logs_thread_id), image_url=image_url or "", pending_members=pending_members,
                ping_message_id=int(ping_message_id or 0)
            )
            
            await save_plus_state(message_id, channel_id, state)
            
            main_channel = guild.get_channel(int(channel_id))
            if main_channel:
                try:
                    main_msg = await main_channel.fetch_message(int(message_id))
                    view = PlusEventView(self.bot, state)
                    view.message = main_msg
                    embed = await view.build_embed(guild)
                    await main_msg.edit(embed=embed, view=view)
                except Exception: pass

    # ==========================================
    # УДАЛЕНИЕ ПИНГА РОЛЕЙ ПРИ РУЧНОМ УДАЛЕНИИ ЭМБЕДА
    # ==========================================
    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: disnake.RawMessageDeleteEvent):
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute(
                "SELECT channel_id, ping_message_id FROM active_plus_events WHERE message_id = ?",
                (str(payload.message_id),),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return
            channel_id, ping_message_id = row
            await db.execute(
                "DELETE FROM active_plus_events WHERE message_id = ?",
                (str(payload.message_id),),
            )
            await db.commit()

        if not ping_message_id or str(ping_message_id) in ("0", ""):
            return
        channel = self.bot.get_channel(int(channel_id))
        if not channel:
            return
        try:
            ping_msg = await channel.fetch_message(int(ping_message_id))
            await ping_msg.delete()
        except Exception:
            pass

    @tasks.loop(minutes=1)
    async def auto_update_loop(self):
        # 1. ОБНОВЛЕНИЕ ПАНЕЛИ БАНОВ
        await update_ban_panel(self.bot)

        # 2. ОБНОВЛЕНИЕ СТАТИСТИКИ
        stats_channel = self.bot.get_channel(config.CAPT_STATS_CHANNEL_ID)
        if stats_channel:
            async with _STATS_LOCK:
                data = _stats_load()
                emb = _build_stats_embed(data)
                await _update_or_send_stats(self.bot, stats_channel, emb, data)

        # 3. ОБНОВЛЕНИЕ АКТИВНЫХ СБОРОВ
        now = datetime.now(timezone.utc).timestamp()
        async with aiosqlite.connect("data/database.sqlite") as db:
            async with db.execute("SELECT message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_members, ping_message_id FROM active_plus_events WHERE revealed = 0 OR warned = 0") as cursor:
                rows = await cursor.fetchall()
                
            for row in rows:
                message_id, channel_id, event_type, ts, base_slots, extra_slots, closed, members_json, revealed, warned, logs_enabled, logs_thread_id, image_url, pending_json, ping_message_id = row
                
                channel = self.bot.get_channel(int(channel_id))
                if not channel: continue
                guild = channel.guild
                
                try:
                    msg = await channel.fetch_message(int(message_id))
                    members = json.loads(members_json)
                    try: pending_members = json.loads(pending_json)
                    except: pending_members = []
                    
                    state = PlusState(
                        event_type, ts, base_slots, extra_slots, bool(closed), members=members, 
                        revealed=bool(revealed), warned=bool(warned), logs_enabled=bool(logs_enabled), logs_thread_id=int(logs_thread_id), image_url=image_url or "", pending_members=pending_members,
                        ping_message_id=int(ping_message_id or 0)
                    )
                    
                    changed = False
                    
                    if not state.warned and now >= (ts - 300) and now < ts:
                        view = PlusEventView(self.bot, state)
                        view.message = msg
                        await view.notify_5_min_warning()
                        state.warned = True
                        changed = True
                        
                    if not state.revealed and now >= ts:
                        state.revealed = True
                        view = PlusEventView(self.bot, state)
                        view.message = msg
                        
                        embed = await view.build_embed(guild)
                        await msg.edit(embed=embed, view=view)
                        changed = True
                        
                    if changed:
                        await db.execute("UPDATE active_plus_events SET revealed = ?, warned = ? WHERE message_id = ?", (int(state.revealed), int(state.warned), str(message_id)))
                        await db.commit()
                        
                except Exception:
                    pass
    
    @commands.slash_command(name="plus", description="Создать PLUS сбор")
    async def plus(
        self, 
        inter: disnake.ApplicationCommandInteraction,
        event_type: str = commands.Param(name="тип", choices=["CAPT", "MCL", "ВЗЗ", "ВЗМ"], description="Выберите тип мероприятия"),
        date_time: str = commands.Param(name="время", description="Время и дата по МСК (например: 25.10 18:30 или 18:30)"),
        base_slots: int = commands.Param(name="количество", description="Основные слоты (количество людей)"),
        extra_slots: int = commands.Param(name="доп_слоты", default=0, description="Дополнительные резервные слоты"),
        image_file: disnake.Attachment = commands.Param(name="картинка_файл", default=None, description="Загрузить картинку с устройства (ПК/Телефон)"),
        image_link: str = commands.Param(name="картинка_ссылка", default=None, description="Вставить ссылку на картинку (из интернета)")
    ):
        if _is_banned(inter):
            return await inter.response.send_message(f"{e('REJECT')}Вы заблокированы и не можете создавать сборы.", ephemeral=True)
            
        now = datetime.now(TZ_UTC3)
        dt_str = date_time.strip()
        target_dt = None
        
        if re.match(r"^\d{1,2}:\d{2}$", dt_str):
            try:
                hour, minute = map(int, dt_str.split(":"))
                target_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target_dt <= now:
                    target_dt += timedelta(days=1)
            except Exception:
                pass
        else:
            formats = ["%d.%m %H:%M", "%d.%m.%Y %H:%M", "%d/%m %H:%M", "%d-%m %H:%M"]
            for fmt in formats:
                try:
                    parsed = datetime.strptime(dt_str, fmt)
                    year = parsed.year if "%Y" in fmt else now.year
                    target_dt = now.replace(year=year, month=parsed.month, day=parsed.day, hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
                    break
                except ValueError:
                    continue
                    
        if not target_dt:
            return await inter.response.send_message(f"{e('ERROR')}Неверный формат времени! Введите `ЧЧ:ММ` (на сегодня/завтра) или `ДД.ММ ЧЧ:ММ` (например: 25.10 18:30).", ephemeral=True)
            
        ts = int(target_dt.timestamp())
        
        if base_slots <= 0 or extra_slots < 0:
            return await inter.response.send_message(f"{e('ERROR')}Слоты должны быть положительными числами!", ephemeral=True)
            
        final_image_url = ""
        if image_file:
            final_image_url = image_file.url
        elif image_link:
            final_image_url = image_link.strip()
            
        await inter.response.defer(ephemeral=True)
        
        state = PlusState(event_type=event_type, ts=ts, base_slots=base_slots, extra_slots=extra_slots, image_url=final_image_url)
        
        publish_channel = inter.channel

        event_view = PlusEventView(self.bot, state)
        await event_view.ping_main_role(publish_channel)
        msg = await publish_channel.send(embed=await event_view.build_embed(inter.guild), view=event_view)
        
        event_view.message = msg
        
        try:
            thread = await msg.create_thread(name=f"сбор-{event_type}".lower(), auto_archive_duration=1440)
            state.logs_enabled = True
            state.logs_thread_id = thread.id
            
            await thread.edit(locked=False) 
            
            await thread.send(f"{e('OPEN')}**Ветка сбора открыта!**\nИгроки могут нажать кнопку «Присоединиться» под основным сообщением, и бот тегнет их здесь.")
            await msg.edit(embed=await event_view.build_embed(inter.guild))
        except Exception:
            pass 
            
        await save_plus_state(msg.id, msg.channel.id, state)
        
        await inter.followup.send(f"{e('SUCCESS')}Сбор успешно создан и опубликован!\n[🔗 Перейти к сообщению]({msg.jump_url})", ephemeral=True)

    # ==========================================
    # КОМАНДЫ ДЛЯ BAN CAPT
    # ==========================================
    @commands.slash_command(name="bancapt", description="Управление BAN CAPT")
    async def bancapt_base(self, inter): pass
    
    @bancapt_base.sub_command(name="setup_panel", description="[АДМИН] Установить панель BAN CAPT в текущий канал")
    async def bancapt_setup(self, inter: disnake.ApplicationCommandInteraction):
        if not inter.author.guild_permissions.administrator:
            return await inter.response.send_message(f"{e('REJECT')}Только для администраторов.", ephemeral=True)
            
        embed = disnake.Embed(title="Список заблокированных - BAN CAPT", description="Загрузка...", color=INVISIBLE_COLOR)
        await inter.response.send_message("Создаю панель...", ephemeral=True)
        msg = await inter.channel.send(embed=embed)
        
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute("INSERT OR REPLACE INTO ban_config (key, value) VALUES ('channel_id', ?)", (str(inter.channel.id),))
            await db.execute("INSERT OR REPLACE INTO ban_config (key, value) VALUES ('message_id', ?)", (str(msg.id),))
            await db.commit()
            
        await update_ban_panel(self.bot)

    @bancapt_base.sub_command(name="add", description="[АДМИН] Выдать BAN CAPT игроку")
    async def bancapt_add(self, inter: disnake.ApplicationCommandInteraction, user: disnake.Member, days: int = commands.Param(description="На сколько дней выдать блокировку?"), reason: str = commands.Param(description="Причина бана")):
        if not _has_settings_access(inter.author):
            return await inter.response.send_message(f"{e('REJECT')}Нет прав.", ephemeral=True)
            
        if days <= 0:
            return await inter.response.send_message(f"{e('ERROR')}Срок должен быть больше 0.", ephemeral=True)
            
        expire_ts = int(time.time()) + (days * 86400)
        
        role = inter.guild.get_role(int(config.BAN_CAPT_ROLE_ID))
        if role:
            try: await user.add_roles(role, reason=f"Выдал: {inter.author.name} | {reason}")
            except: pass
            
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute("INSERT OR REPLACE INTO banned_users (user_id, admin_id, reason, expire_ts) VALUES (?, ?, ?, ?)", (str(user.id), str(inter.author.id), reason, expire_ts))
            await db.commit()
            
        await inter.response.send_message(f"{e('SUCCESS')}Пользователь {user.mention} получил BAN CAPT на {days} дн.", ephemeral=True)
        await update_ban_panel(self.bot)

    @bancapt_base.sub_command(name="remove", description="[АДМИН] Снять BAN CAPT досрочно")
    async def bancapt_remove(self, inter: disnake.ApplicationCommandInteraction, user: disnake.Member):
        if not _has_settings_access(inter.author):
            return await inter.response.send_message(f"{e('REJECT')}Нет прав.", ephemeral=True)
            
        role = inter.guild.get_role(int(config.BAN_CAPT_ROLE_ID))
        if role:
            try: await user.remove_roles(role, reason="Снято досрочно")
            except: pass
            
        async with aiosqlite.connect("data/database.sqlite") as db:
            await db.execute("DELETE FROM banned_users WHERE user_id = ?", (str(user.id),))
            await db.commit()
            
        await inter.response.send_message(f"{e('SUCCESS')}С {user.mention} снят BAN CAPT.", ephemeral=True)
        await update_ban_panel(self.bot)


def setup(bot): bot.add_cog(PlusCog(bot))