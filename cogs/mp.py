import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import json
import os

# ── Configuration ──────────────────────────────────────────────────────────────

# Only members with this role name can add/subtract MP
MP_MANAGER_ROLE_NAME = "MP Points Perm"

LOG_CHANNEL_NAME = "mod-log"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MP_FILE  = os.path.join(DATA_DIR, "mp_points.json")

# Thresholds → role IDs. Only one is held at a time.
# Sorted descending so we always assign the highest earned tier.
MP_TIERS: list[tuple[int, int]] = [
    (50, 1463019534905769985),
    (25, 1463019425476382884),
    (10, 1463019088145158250),
    (5,  1463018961871569032),
    (0,  1463018842816122997),
]

ALL_TIER_IDS: set[int] = {role_id for _, role_id in MP_TIERS}

# ── Persistence ────────────────────────────────────────────────────────────────

def load_mp() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(MP_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_mp(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MP_FILE, "w") as f:
        json.dump(data, f, indent=2)

mp_data: dict = {}  # {guild_id: {user_id: int}}


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_points(guild_id: int, user_id: int) -> int:
    return mp_data.get(str(guild_id), {}).get(str(user_id), 0)

def set_points(guild_id: int, user_id: int, points: int):
    mp_data.setdefault(str(guild_id), {})[str(user_id)] = max(0, points)
    save_mp(mp_data)

def tier_for(points: int) -> tuple[int, int]:
    """Return the (threshold, role_id) for the highest earned tier."""
    for threshold, role_id in MP_TIERS:
        if points >= threshold:
            return threshold, role_id
    return MP_TIERS[-1]  # fallback: 0 MP role

def is_mp_manager():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        return any(r.name == MP_MANAGER_ROLE_NAME for r in interaction.user.roles)
    return app_commands.check(predicate)

async def update_mp_role(member: discord.Member, points: int):
    """Strip all tier roles then assign the correct one for the given point total."""
    _, correct_id = tier_for(points)

    roles_to_remove = [r for r in member.roles if r.id in ALL_TIER_IDS and r.id != correct_id]
    correct_role    = member.guild.get_role(correct_id)

    if roles_to_remove:
        await member.remove_roles(*roles_to_remove, reason="MP tier update")

    if correct_role and correct_role not in member.roles:
        await member.add_roles(correct_role, reason=f"MP tier reached: {points} MP")


class MP(commands.Cog):
    """MP (Moderation Points) system with tiered role rewards."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global mp_data
        mp_data = load_mp()

    async def get_log(self, guild: discord.Guild):
        return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        ch = await self.get_log(guild)
        if ch:
            await ch.send(embed=embed)

    def mp_log_embed(
        self,
        actor: discord.Member,
        target: discord.Member,
        action: str,
        amount: int,
        old: int,
        new: int,
        reason: str,
        color: discord.Color
    ) -> discord.Embed:
        embed = discord.Embed(title=f"⭐ MP — {action}", color=color, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Moderator", value=actor.mention)
        embed.add_field(name="Member",    value=target.mention)
        embed.add_field(name="Change",    value=f"`{old} MP` → `{new} MP` ({'+' if amount >= 0 else ''}{amount})", inline=False)
        embed.add_field(name="Reason",    value=reason, inline=False)
        _, tier_role_id = tier_for(new)
        tier_role = target.guild.get_role(tier_role_id)
        embed.add_field(name="Current Tier", value=tier_role.mention if tier_role else f"`{tier_role_id}`")
        return embed

    # ── /mp group ──────────────────────────────────────────────────────────────

    mp_group = app_commands.Group(name="mp", description="MP (Moderation Points) commands.")

    @mp_group.command(name="add", description="Add MP to a moderator.")
    @app_commands.describe(member="Moderator to award", amount="Points to add", reason="Reason")
    @is_mp_manager()
    async def mp_add(self, interaction: discord.Interaction, member: discord.Member, amount: int, reason: str = "No reason provided."):
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be a positive number.", ephemeral=True)

        old = get_points(interaction.guild.id, member.id)
        new = old + amount
        set_points(interaction.guild.id, member.id, new)
        await update_mp_role(member, new)

        _, tier_id = tier_for(new)
        tier_role  = interaction.guild.get_role(tier_id)

        await interaction.response.send_message(
            f"✅ Added **{amount} MP** to {member.mention}. They now have **{new} MP**."
            + (f" New tier: {tier_role.mention}" if tier_role and tier_for(old)[1] != tier_id else ""),
            ephemeral=True
        )

        embed = self.mp_log_embed(interaction.user, member, "Points Added", amount, old, new, reason, discord.Color.green())
        await self.send_log(interaction.guild, embed)

        # Notify member if they hit a new tier
        if tier_for(old)[0] != tier_for(new)[0] and tier_role:
            try:
                await member.send(
                    f"🌟 You've reached a new MP tier in **{interaction.guild.name}**!\n"
                    f"You now have **{new} MP** and have been awarded the **{tier_role.name}** role."
                )
            except discord.Forbidden:
                pass

    @mp_group.command(name="remove", description="Remove MP from a moderator.")
    @app_commands.describe(member="Moderator to deduct from", amount="Points to remove", reason="Reason")
    @is_mp_manager()
    async def mp_remove(self, interaction: discord.Interaction, member: discord.Member, amount: int, reason: str = "No reason provided."):
        if amount <= 0:
            return await interaction.response.send_message("❌ Amount must be a positive number.", ephemeral=True)

        old = get_points(interaction.guild.id, member.id)
        new = max(0, old - amount)
        set_points(interaction.guild.id, member.id, new)
        await update_mp_role(member, new)

        await interaction.response.send_message(
            f"✅ Removed **{amount} MP** from {member.mention}. They now have **{new} MP**.",
            ephemeral=True
        )

        embed = self.mp_log_embed(interaction.user, member, "Points Removed", -amount, old, new, reason, discord.Color.red())
        await self.send_log(interaction.guild, embed)

        # Notify member if they dropped a tier
        if tier_for(old)[0] != tier_for(new)[0]:
            _, tier_id = tier_for(new)
            tier_role  = interaction.guild.get_role(tier_id)
            try:
                await member.send(
                    f"📉 Your MP tier in **{interaction.guild.name}** has changed.\n"
                    f"You now have **{new} MP**"
                    + (f" and hold the **{tier_role.name}** role." if tier_role else ".")
                )
            except discord.Forbidden:
                pass

    @mp_group.command(name="set", description="Set a moderator's MP to an exact value.")
    @app_commands.describe(member="Moderator to set", points="Exact point value", reason="Reason")
    @is_mp_manager()
    async def mp_set(self, interaction: discord.Interaction, member: discord.Member, points: int, reason: str = "No reason provided."):
        if points < 0:
            return await interaction.response.send_message("❌ Points cannot be negative.", ephemeral=True)

        old = get_points(interaction.guild.id, member.id)
        set_points(interaction.guild.id, member.id, points)
        await update_mp_role(member, points)

        await interaction.response.send_message(
            f"✅ Set {member.mention}'s MP to **{points}**.",
            ephemeral=True
        )

        diff  = points - old
        embed = self.mp_log_embed(
            interaction.user, member, "Points Set",
            diff, old, points, reason,
            discord.Color.blurple()
        )
        await self.send_log(interaction.guild, embed)

    @mp_group.command(name="check", description="Check a member's current MP and tier.")
    @app_commands.describe(member="Member to check (leave blank for yourself)")
    async def mp_check(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        points = get_points(interaction.guild.id, target.id)
        threshold, tier_id = tier_for(points)
        tier_role = interaction.guild.get_role(tier_id)

        # Find next tier
        next_tier = None
        for t, rid in reversed(MP_TIERS):
            if t > points:
                next_tier = (t, rid)
                break

        embed = discord.Embed(
            title=f"⭐ MP — {target.display_name}",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Points",       value=f"**{points} MP**")
        embed.add_field(name="Current Tier", value=tier_role.mention if tier_role else f"`{tier_id}`")
        if next_tier:
            next_role = interaction.guild.get_role(next_tier[1])
            needed    = next_tier[0] - points
            embed.add_field(
                name="Next Tier",
                value=f"{next_role.mention if next_role else next_tier[0]} — **{needed} MP** away",
                inline=False
            )
        else:
            embed.add_field(name="Next Tier", value="🏆 Max tier reached!", inline=False)

        await interaction.response.send_message(embed=embed)

    @mp_group.command(name="leaderboard", description="Show the top MP earners in the server.")
    async def mp_leaderboard(self, interaction: discord.Interaction):
        guild_data = mp_data.get(str(interaction.guild.id), {})
        if not guild_data:
            return await interaction.response.send_message("No MP data yet.", ephemeral=True)

        sorted_members = sorted(guild_data.items(), key=lambda x: x[1], reverse=True)[:10]

        embed = discord.Embed(title="🏆 MP Leaderboard", color=discord.Color.gold(), timestamp=datetime.now(timezone.utc))
        medals = ["🥇", "🥈", "🥉"]
        lines  = []
        for i, (uid, pts) in enumerate(sorted_members):
            member = interaction.guild.get_member(int(uid))
            name   = member.display_name if member else f"Unknown ({uid})"
            medal  = medals[i] if i < 3 else f"`#{i+1}`"
            _, tid = tier_for(pts)
            tr     = interaction.guild.get_role(tid)
            tier   = tr.name if tr else "—"
            lines.append(f"{medal} **{name}** — {pts} MP *(Tier: {tier})*")

        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    @mp_group.command(name="reset", description="Reset a moderator's MP to 0.")
    @app_commands.describe(member="Member to reset", reason="Reason")
    @is_mp_manager()
    async def mp_reset(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        old = get_points(interaction.guild.id, member.id)
        set_points(interaction.guild.id, member.id, 0)
        await update_mp_role(member, 0)
        await interaction.response.send_message(f"✅ Reset {member.mention}'s MP to 0.", ephemeral=True)
        embed = self.mp_log_embed(interaction.user, member, "Points Reset", -old, old, 0, reason, discord.Color.dark_red())
        await self.send_log(interaction.guild, embed)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("❌ You need the **MP Points Perm** role to use this command.", ephemeral=True)
        else:
            raise error


async def setup(bot: commands.Bot):
    await bot.add_cog(MP(bot))
