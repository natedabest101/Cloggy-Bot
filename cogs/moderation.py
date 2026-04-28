import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta, datetime, timezone
import re
import asyncio
import json
import os

BANNED_ROLE_NAME = "Banned"
APPEAL_DAYS = 30
MOD_ROLE_ID = 1454758126912933970
LOG_CHANNEL_NAME = "mod-log"

warnings: dict[int, dict[int, list[dict]]] = {}
pending_bans: dict[int, dict[int, asyncio.Task]] = {}

def parse_duration(duration: str) -> timedelta | None:
    match = re.fullmatch(r"(\d+)([smhd])", duration.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    return timedelta(
        seconds=value if unit == "s" else
        value * 60 if unit == "m" else
        value * 3600 if unit == "h" else
        value * 86400
    )

def is_mod():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        role = interaction.guild.get_role(MOD_ROLE_ID)
        if role is None:
            return False
        return role in interaction.user.roles
    return app_commands.check(predicate)

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_log(self, guild: discord.Guild):
        return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

    async def dispatch_log(self, guild, moderator, target, action, reason):
        self.bot.dispatch("mod_action", guild, moderator, target, action, reason)

    # ── /kick ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="Member to kick", reason="Reason for the kick")
    @is_mod()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        if member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message("❌ You can't kick someone with an equal or higher role.", ephemeral=True)
        await member.kick(reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"👢 **{member}** has been kicked. Reason: {reason}")
        await self.dispatch_log(interaction.guild, interaction.user, member, "kick", reason)

    # ── /ban ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Stage a ban with a 30-day appeal window.")
    @app_commands.describe(member="Member to ban", reason="Reason for the ban")
    @is_mod()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        await interaction.response.defer()
        if member.top_role >= interaction.user.top_role:
            return await interaction.followup.send("❌ You can't ban someone with an equal or higher role.", ephemeral=True)
        banned_role = discord.utils.get(interaction.guild.roles, name=BANNED_ROLE_NAME)
        if not banned_role:
            return await interaction.followup.send(f"❌ Could not find role **{BANNED_ROLE_NAME}**. Please create it first.", ephemeral=True)
        roles_to_remove = [
            r for r in member.roles
            if r != interaction.guild.default_role
            and r < interaction.user.top_role
            and r != banned_role
        ]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason=f"Staged ban by {interaction.user}")
        await member.add_roles(banned_role, reason=f"Staged ban by {interaction.user}: {reason}")
        deadline = datetime.now(timezone.utc) + timedelta(days=APPEAL_DAYS)
        deadline_str = discord.utils.format_dt(deadline, "D")
        try:
            await member.send(
                f"⚠️ You have been **staged for a ban** in **{interaction.guild.name}**.\n"
                f"**Reason:** {reason}\n\n"
                f"You have until **{deadline_str}** to appeal. If not accepted, you will be permanently banned."
            )
            dm_sent = True
        except discord.Forbidden:
            dm_sent = False
        dm_note = " (Could not DM them.)" if not dm_sent else ""
        await interaction.followup.send(f"🔨 **{member}** staged for ban. {APPEAL_DAYS} days to appeal.{dm_note}")
        await self.dispatch_log(interaction.guild, interaction.user, member, f"staged ban ({APPEAL_DAYS}d appeal window)", reason)
        guild_bans = pending_bans.setdefault(interaction.guild.id, {})
        if member.id in guild_bans:
            guild_bans[member.id].cancel()
        async def execute_ban():
            await asyncio.sleep(APPEAL_DAYS * 86400)
            target = interaction.guild.get_member(member.id)
            if target:
                try:
                    await interaction.guild.ban(target, reason=f"Appeal window expired. Original: {reason}", delete_message_days=1)
                    await self.dispatch_log(interaction.guild, self.bot.user, target, "ban (appeal expired)", reason)
                except discord.Forbidden:
                    pass
            pending_bans.get(interaction.guild.id, {}).pop(member.id, None)
        guild_bans[member.id] = asyncio.create_task(execute_ban())

    # ── /pardon ────────────────────────────────────────────────────────────────

    @app_commands.command(name="pardon", description="Cancel a staged ban and remove the Banned role.")
    @app_commands.describe(member="Member to pardon", reason="Reason for the pardon")
    @is_mod()
    async def pardon(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Appeal accepted."):
        banned_role = discord.utils.get(interaction.guild.roles, name=BANNED_ROLE_NAME)
        task = pending_bans.get(interaction.guild.id, {}).pop(member.id, None)
        if task:
            task.cancel()
        if banned_role and banned_role in member.roles:
            await member.remove_roles(banned_role, reason=f"Pardon by {interaction.user}: {reason}")
        await interaction.response.send_message(f"✅ **{member}**'s staged ban cancelled. Reason: {reason}")
        await self.dispatch_log(interaction.guild, interaction.user, member, "pardon", reason)
        try:
            await member.send(f"✅ Your ban appeal in **{interaction.guild.name}** has been **accepted**.\nReason: {reason}")
        except discord.Forbidden:
            pass

    # ── /pendingbans ───────────────────────────────────────────────────────────

    @app_commands.command(name="pendingbans", description="List all members currently in the appeal window.")
    @is_mod()
    async def pendingbans(self, interaction: discord.Interaction):
        guild_bans = pending_bans.get(interaction.guild.id, {})
        if not guild_bans:
            return await interaction.response.send_message("✅ No staged bans pending.")
        lines = []
        for uid in guild_bans:
            m = interaction.guild.get_member(uid)
            lines.append(f"• {m} (`{uid}`)" if m else f"• Unknown (`{uid}`)")
        embed = discord.Embed(title=f"⏳ Pending Bans ({len(guild_bans)})", description="\n".join(lines), color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    # ── /unban ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Unban a fully-banned user by their ID.")
    @app_commands.describe(user_id="Discord user ID to unban")
    @is_mod()
    async def unban(self, interaction: discord.Interaction, user_id: str):
        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        try:
            await interaction.guild.unban(discord.Object(id=uid))
            await interaction.response.send_message(f"✅ Unbanned user `{uid}`.")
        except discord.NotFound:
            await interaction.response.send_message("❌ That user is not banned.", ephemeral=True)

    # ── /mute ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="mute", description="Timeout a member. Duration: 10s, 5m, 2h, 1d (max 28d).")
    @app_commands.describe(member="Member to mute", duration="Duration e.g. 10m, 2h, 1d", reason="Reason")
    @is_mod()
    async def mute(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "No reason provided."):
        delta = parse_duration(duration)
        if not delta:
            return await interaction.response.send_message("❌ Invalid duration. Use e.g. `10m`, `2h`, `1d`.", ephemeral=True)
        if delta > timedelta(days=28):
            return await interaction.response.send_message("❌ Timeout cannot exceed 28 days.", ephemeral=True)
        await member.timeout(delta, reason=f"{interaction.user}: {reason}")
        await interaction.response.send_message(f"🔇 **{member}** muted for **{duration}**. Reason: {reason}")
        await self.dispatch_log(interaction.guild, interaction.user, member, f"mute ({duration})", reason)

    # ── /unmute ────────────────────────────────────────────────────────────────

    @app_commands.command(name="unmute", description="Remove a timeout from a member.")
    @app_commands.describe(member="Member to unmute")
    @is_mod()
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await interaction.response.send_message(f"🔊 **{member}**'s timeout removed.")

    # ── /warn ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    @is_mod()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        guild_warns = warnings.setdefault(interaction.guild.id, {})
        user_warns = guild_warns.setdefault(member.id, [])
        user_warns.append({"moderator": str(interaction.user), "reason": reason})
        count = len(user_warns)
        await interaction.response.send_message(f"⚠️ **{member}** warned (#{count}). Reason: {reason}")
        await self.dispatch_log(interaction.guild, interaction.user, member, f"warn (#{count})", reason)
        try:
            await member.send(f"⚠️ You have been warned in **{interaction.guild.name}**.\nReason: {reason}\nThis is warning #{count}.")
        except discord.Forbidden:
            pass

    # ── /warnings ──────────────────────────────────────────────────────────────

    @app_commands.command(name="warnings", description="View warnings for a member.")
    @app_commands.describe(member="Member to check")
    @is_mod()
    async def warnings_cmd(self, interaction: discord.Interaction, member: discord.Member):
        user_warns = warnings.get(interaction.guild.id, {}).get(member.id, [])
        if not user_warns:
            return await interaction.response.send_message(f"✅ **{member}** has no warnings.")
        embed = discord.Embed(title=f"Warnings for {member}", color=discord.Color.orange())
        for i, w in enumerate(user_warns, 1):
            embed.add_field(name=f"#{i} — {w['moderator']}", value=w["reason"], inline=False)
        await interaction.response.send_message(embed=embed)

    # ── /clearwarnings ─────────────────────────────────────────────────────────

    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member.")
    @app_commands.describe(member="Member to clear warnings for")
    @is_mod()
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        warnings.get(interaction.guild.id, {}).pop(member.id, None)
        await interaction.response.send_message(f"✅ Cleared all warnings for **{member}**.")
        await self.dispatch_log(interaction.guild, interaction.user, member, "clearwarnings", "All warnings cleared.")

    # ── /purge ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="purge", description="Bulk delete messages (1–200). Optionally filter by member.")
    @app_commands.describe(amount="Number of messages to delete", member="Only delete messages from this member")
    @is_mod()
    async def purge(self, interaction: discord.Interaction, amount: int, member: discord.Member = None):
        if amount < 1 or amount > 200:
            return await interaction.response.send_message("❌ Amount must be between 1 and 200.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        check = (lambda m: m.author == member) if member else None
        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(f"🗑️ Deleted {len(deleted)} message(s).", ephemeral=True)

    # ── Error handler ──────────────────────────────────────────────────────────

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        else:
            raise error

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
