import discord
from discord import app_commands
from discord.ext import commands
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import re
import json
import os

SPAM_MESSAGE_LIMIT    = 5
SPAM_INTERVAL_SECONDS = 5
SPAM_MUTE_MINUTES     = 5
MOD_ROLE_ID           = 1454758126912933970
LOG_CHANNEL_NAME      = "logging"

IMMUNE_ROLE_IDS: set[int]    = {MOD_ROLE_ID}
IMMUNE_CHANNEL_IDS: set[int] = set()

DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")
WORDS_FILE = os.path.join(DATA_DIR, "blocked_words.json")

def load_words() -> list[str]:
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(WORDS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ["badword1", "badword2"]

def save_words(words: list[str]):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(WORDS_FILE, "w") as f:
        json.dump(words, f, indent=2)

BLOCKED_WORDS: list[str] = load_words()

LEET_MAP: dict[str, str] = {
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a",
    "5": "s", "7": "t", "8": "b", "9": "g",
    "@": "a", "$": "s", "!": "i", "|": "i", "+": "t",
    "(": "c", ")": "o", "<": "c", ">": "o",
    "α": "a", "β": "b", "ε": "e", "ι": "i", "ο": "o",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ζ": "z",
    "*": "", ".": "", "-": "", "_": "",
}
STRIP_PATTERN = re.compile(r"[\u00ad\u200b\u200c\u200d\u2060\uFEFF]")
_LEET_TABLE   = str.maketrans(LEET_MAP)

def normalise(text: str) -> str:
    text = STRIP_PATTERN.sub("", text)
    text = text.lower()
    text = text.translate(_LEET_TABLE)
    text = re.sub(r"(.)\1+", r"\1", text)
    text = re.sub(r"[^a-z]", "", text)
    return text

def build_pattern(words: list[str]) -> re.Pattern:
    if not words:
        return re.compile(r"(?!)")
    return re.compile("(" + "|".join(re.escape(normalise(w)) for w in words) + ")")

def build_fuzzy_pattern(words: list[str]) -> re.Pattern:
    if not words:
        return re.compile(r"(?!)")
    parts = []
    for w in words:
        n = normalise(w)
        parts.append(re.escape(n))
        if len(n) >= 4:
            skeleton = n[0] + re.sub(r"[aeiou]", "", n[1:-1]) + n[-1]
            if skeleton != n and len(skeleton) >= 3:
                parts.append(re.escape(skeleton))
    return re.compile("(" + "|".join(set(parts)) + ")")

BLOCKED_PATTERN = build_pattern(BLOCKED_WORDS)
FUZZY_PATTERN   = build_fuzzy_pattern(BLOCKED_WORDS)

MULTILANG_WORDS: dict[str, list[str]] = {
    "es": [], "fr": [], "pt": [], "de": [], "ar": [],
    "ru": [], "ja": [], "zh": [], "hi": [], "it": [],
    "nl": [], "ko": [], "pl": [], "tr": [],
}
_all_multilang = [w for words in MULTILANG_WORDS.values() for w in words]
MULTILANG_PATTERN = build_pattern(_all_multilang) if _all_multilang else re.compile(r"(?!)")
_WORD_TO_LANG: dict[str, str] = {
    normalise(w): lang
    for lang, words in MULTILANG_WORDS.items()
    for w in words
}
LANG_NAMES = {
    "es": "Spanish", "fr": "French", "pt": "Portuguese", "de": "German",
    "ar": "Arabic",  "ru": "Russian","ja": "Japanese",  "zh": "Mandarin",
    "hi": "Hindi",   "it": "Italian","nl": "Dutch",     "ko": "Korean",
    "pl": "Polish",  "tr": "Turkish",
}

message_timestamps: dict[int, dict[int, list[datetime]]] = defaultdict(lambda: defaultdict(list))

def is_mod():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        role = interaction.guild.get_role(MOD_ROLE_ID)
        return role is not None and role in interaction.user.roles
    return app_commands.check(predicate)

class AutoMod(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def is_immune(self, message: discord.Message) -> bool:
        if message.author.bot:
            return True
        if message.channel.id in IMMUNE_CHANNEL_IDS:
            return True
        if any(r.id in IMMUNE_ROLE_IDS for r in getattr(message.author, "roles", [])):
            return True
        return False

    async def get_log(self, guild: discord.Guild):
        return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

    async def log_embed(self, guild: discord.Guild, embed: discord.Embed):
        ch = await self.get_log(guild)
        if ch:
            await ch.send(embed=embed)

    async def warn_and_delete(self, message: discord.Message, reason: str):
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            await message.channel.send(f"⚠️ {message.author.mention} — {reason}", delete_after=8)
        except discord.HTTPException:
            pass
        embed = discord.Embed(title="🤖 AutoMod — Blocked", color=discord.Color.red())
        embed.add_field(name="User",    value=f"{message.author.mention} (`{message.author.id}`)")
        embed.add_field(name="Channel", value=message.channel.mention)
        embed.add_field(name="Reason",  value=reason, inline=False)
        embed.add_field(name="Content", value=message.content[:512] or "*(empty)*", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await self.log_embed(message.guild, embed)

    async def log_possible_violation(self, message: discord.Message, detail: str):
        embed = discord.Embed(title="🔍 Possible Language Violation", color=discord.Color.gold())
        embed.add_field(name="User",    value=f"{message.author.mention} (`{message.author.id}`)")
        embed.add_field(name="Channel", value=message.channel.mention)
        embed.add_field(name="Detail",  value=detail, inline=False)
        embed.add_field(name="Content", value=message.content[:512] or "*(empty)*", inline=False)
        embed.add_field(name="Jump",    value=f"[Go to message]({message.jump_url})", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await self.log_embed(message.guild, embed)

    async def check_bad_words(self, message: discord.Message) -> bool:
        if BLOCKED_PATTERN.search(normalise(message.content)):
            await self.warn_and_delete(message, "Your message contained a prohibited word.")
            return True
        return False

    async def check_fuzzy(self, message: discord.Message) -> bool:
        n = normalise(message.content)
        match = FUZZY_PATTERN.search(n)
        if match:
            await self.log_possible_violation(message, f"Possible embedded blocked word — fragment: `{match.group()}`")
            return True
        return False

    async def check_multilang(self, message: discord.Message) -> bool:
        match = MULTILANG_PATTERN.search(normalise(message.content))
        if match:
            lang_name = LANG_NAMES.get(_WORD_TO_LANG.get(match.group(), ""), "Unknown")
            await self.warn_and_delete(message, f"Your message contained prohibited language ({lang_name}).")
            return True
        return False

    async def check_spam(self, message: discord.Message) -> bool:
        uid = message.author.id
        gid = message.guild.id
        now = datetime.now(timezone.utc)
        timestamps = message_timestamps[gid][uid]
        timestamps[:] = [t for t in timestamps if (now - t).total_seconds() < SPAM_INTERVAL_SECONDS]
        timestamps.append(now)
        if len(timestamps) >= SPAM_MESSAGE_LIMIT:
            timestamps.clear()
            try:
                await message.author.timeout(timedelta(minutes=SPAM_MUTE_MINUTES), reason="AutoMod: spam")
            except discord.Forbidden:
                pass
            await self.warn_and_delete(message, f"Sending messages too quickly. Muted for {SPAM_MUTE_MINUTES} minute(s).")
            return True
        return False

    INVITE_PATTERN = re.compile(r"(discord\.gg|discord\.com/invite)/\S+", re.IGNORECASE)

    async def check_invites(self, message: discord.Message) -> bool:
        if self.INVITE_PATTERN.search(message.content):
            await self.warn_and_delete(message, "External invite links are not allowed here.")
            return True
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or self.is_immune(message):
            return
        if await self.check_bad_words(message): return
        if await self.check_multilang(message):  return
        if await self.check_spam(message):       return
        if await self.check_invites(message):    return
        await self.check_fuzzy(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or self.is_immune(after):
            return
        if await self.check_bad_words(after): return
        if await self.check_multilang(after):  return
        if await self.check_invites(after):    return
        await self.check_fuzzy(after)

    # ── /automod group ─────────────────────────────────────────────────────────

    automod_group = app_commands.Group(name="automod", description="AutoMod management commands.")

    @automod_group.command(name="config", description="Show current AutoMod configuration.")
    @is_mod()
    async def automod_config(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🤖 AutoMod Config", color=discord.Color.blurple())
        embed.add_field(name="Spam limit",      value=f"{SPAM_MESSAGE_LIMIT} msgs / {SPAM_INTERVAL_SECONDS}s")
        embed.add_field(name="Spam mute",       value=f"{SPAM_MUTE_MINUTES} min")
        embed.add_field(name="Blocked words",   value=str(len(BLOCKED_WORDS)))
        embed.add_field(name="Multilang words", value=str(len(_all_multilang)))
        embed.add_field(name="Leet filter",     value="✅ Enabled")
        embed.add_field(name="Fuzzy scan",      value="✅ Enabled (soft flag)")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="addword", description="Add a word to the block list.")
    @app_commands.describe(word="Word to block (leet variants auto-included)")
    @is_mod()
    async def automod_addword(self, interaction: discord.Interaction, word: str):
        global BLOCKED_PATTERN, FUZZY_PATTERN
        word = word.lower().strip()
        if word in BLOCKED_WORDS:
            return await interaction.response.send_message("That word is already blocked.", ephemeral=True)
        BLOCKED_WORDS.append(word)
        BLOCKED_PATTERN = build_pattern(BLOCKED_WORDS)
        FUZZY_PATTERN   = build_fuzzy_pattern(BLOCKED_WORDS)
        save_words(BLOCKED_WORDS)
        await interaction.response.send_message(f"✅ Added `{word}` to the block list.", ephemeral=True)
        embed = discord.Embed(title="🤖 AutoMod — Word Added", color=discord.Color.orange(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Added by", value=interaction.user.mention)
        embed.add_field(name="Word",     value=f"`{word}`")
        ch = await self.get_log(interaction.guild)
        if ch:
            await ch.send(embed=embed)

    @automod_group.command(name="removeword", description="Remove a word from the block list.")
    @app_commands.describe(word="Word to remove")
    @is_mod()
    async def automod_removeword(self, interaction: discord.Interaction, word: str):
        global BLOCKED_PATTERN, FUZZY_PATTERN
        word = word.lower().strip()
        if word not in BLOCKED_WORDS:
            return await interaction.response.send_message("That word isn't in the block list.", ephemeral=True)
        BLOCKED_WORDS.remove(word)
        BLOCKED_PATTERN = build_pattern(BLOCKED_WORDS)
        FUZZY_PATTERN   = build_fuzzy_pattern(BLOCKED_WORDS)
        save_words(BLOCKED_WORDS)
        await interaction.response.send_message(f"✅ Removed `{word}` from the block list.", ephemeral=True)
        embed = discord.Embed(title="🤖 AutoMod — Word Removed", color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Removed by", value=interaction.user.mention)
        embed.add_field(name="Word",       value=f"`{word}`")
        ch = await self.get_log(interaction.guild)
        if ch:
            await ch.send(embed=embed)

    @automod_group.command(name="listwords", description="DMs you the current blocked word list.")
    @is_mod()
    async def automod_listwords(self, interaction: discord.Interaction):
        if not BLOCKED_WORDS:
            return await interaction.response.send_message("No words are currently blocked.", ephemeral=True)
        word_list = "\n".join(f"{i+1}. {w}" for i, w in enumerate(BLOCKED_WORDS))
        try:
            await interaction.user.send(f"**Blocked words ({len(BLOCKED_WORDS)}):**\n```\n{word_list}\n```")
            await interaction.response.send_message("📬 Sent you the list via DM.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Couldn't DM you — enable DMs from server members.", ephemeral=True)

    @automod_group.command(name="test", description="Test how the filter processes a string.")
    @app_commands.describe(text="Text to test")
    @is_mod()
    async def automod_test(self, interaction: discord.Interaction, text: str):
        n     = normalise(text)
        hard  = BLOCKED_PATTERN.search(n)
        fuzzy = FUZZY_PATTERN.search(n)
        multi = MULTILANG_PATTERN.search(n)
        embed = discord.Embed(title="🔍 Filter Test", color=discord.Color.blurple())
        embed.add_field(name="Input",      value=text, inline=False)
        embed.add_field(name="Normalised", value=n or "*(empty)*", inline=False)
        embed.add_field(name="Hard block", value=f"🚫 `{hard.group()}`" if hard else "✅ No match", inline=False)
        embed.add_field(name="Fuzzy flag", value=f"🟡 `{fuzzy.group()}` (log only)" if (not hard and fuzzy) else ("— " if hard else "✅ No match"), inline=False)
        if multi:
            lang = LANG_NAMES.get(_WORD_TO_LANG.get(multi.group(), ""), "Unknown")
            embed.add_field(name="Multilang", value=f"🚫 `{multi.group()}` ({lang})", inline=False)
        else:
            embed.add_field(name="Multilang", value="✅ No match", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        else:
            raise error

async def setup(bot):
    await bot.add_cog(AutoMod(bot))
