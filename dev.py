import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import json
import os

ANNOUNCEMENTS_CHANNEL = "📣｜𝐆𝐚𝐦𝐞-𝐔𝐩𝐝𝐚𝐭𝐞𝐬"
BUG_REPORTS_CHANNEL   = "👾｜𝐁𝐮𝐠-𝐑𝐞𝐩𝐨𝐫𝐭𝐬"
TASK_BOARD_CHANNEL    = "📜task-board"
LOG_CHANNEL_NAME      = "logging"
DEV_ROLE_ID           = 1454757815473143973
MOD_ROLE_ID           = 1454758126912933970

DATA_DIR   = os.path.join(os.path.dirname(__file__), "..", "data")
BUGS_FILE  = os.path.join(DATA_DIR, "bugs.json")
TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")

def load_json(path, default):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

bugs:  dict = {}
tasks: dict = {}

def is_dev():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        dev_role = interaction.guild.get_role(DEV_ROLE_ID)
        mod_role = interaction.guild.get_role(MOD_ROLE_ID)
        roles = interaction.user.roles
        return (dev_role and dev_role in roles) or (mod_role and mod_role in roles)
    return app_commands.check(predicate)

def is_mod():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            return False
        role = interaction.guild.get_role(MOD_ROLE_ID)
        return role is not None and role in interaction.user.roles
    return app_commands.check(predicate)

class Dev(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global bugs, tasks
        bugs  = load_json(BUGS_FILE,  {})
        tasks = load_json(TASKS_FILE, {})

    def save(self):
        save_json(BUGS_FILE,  bugs)
        save_json(TASKS_FILE, tasks)

    def next_id(self, store: dict, guild_id: str) -> int:
        entries = store.get(guild_id, {})
        return max((int(k) for k in entries), default=0) + 1

    async def get_log(self, guild: discord.Guild):
        return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

    async def send_log(self, guild: discord.Guild, embed: discord.Embed):
        ch = await self.get_log(guild)
        if ch:
            await ch.send(embed=embed)

    def action_log_embed(self, actor: discord.Member, action: str, detail: str, color: discord.Color) -> discord.Embed:
        embed = discord.Embed(title=f"📋 Dev Log — {action}", color=color, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="By", value=actor.mention)
        embed.add_field(name="Detail", value=detail, inline=False)
        return embed

    # ── Update group ───────────────────────────────────────────────────────────

    update_group = app_commands.Group(name="update", description="Post game update announcements.")

    @update_group.command(name="post", description="Post a full versioned game update announcement.")
    @app_commands.describe(version="Version number e.g. 1.4.2", notes="Update notes")
    @is_dev()
    async def update_post(self, interaction: discord.Interaction, version: str, notes: str):
        channel = discord.utils.get(interaction.guild.text_channels, name=ANNOUNCEMENTS_CHANNEL)
        if not channel:
            return await interaction.response.send_message(f"❌ Channel `#{ANNOUNCEMENTS_CHANNEL}` not found.", ephemeral=True)
        embed = discord.Embed(title=f"🎮 Game Update — v{version}", description=notes, color=discord.Color.brand_red(), timestamp=datetime.now(timezone.utc))
        embed.set_footer(text=f"Posted by {interaction.user.display_name}")
        await channel.send("@here", embed=embed)
        await interaction.response.send_message(f"✅ Update v{version} posted to {channel.mention}.", ephemeral=True)
        log = self.action_log_embed(interaction.user, f"Update posted — v{version}", notes[:512], discord.Color.red())
        await self.send_log(interaction.guild, log)

    @update_group.command(name="patch", description="Post a quick patch note.")
    @app_commands.describe(notes="Patch note content")
    @is_dev()
    async def update_patch(self, interaction: discord.Interaction, notes: str):
        channel = discord.utils.get(interaction.guild.text_channels, name=ANNOUNCEMENTS_CHANNEL)
        if not channel:
            return await interaction.response.send_message(f"❌ Channel `#{ANNOUNCEMENTS_CHANNEL}` not found.", ephemeral=True)
        embed = discord.Embed(title="🔧 Patch Notes", description=notes, color=discord.Color.yellow(), timestamp=datetime.now(timezone.utc))
        embed.set_footer(text=f"Posted by {interaction.user.display_name}")
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Patch notes posted to {channel.mention}.", ephemeral=True)
        log = self.action_log_embed(interaction.user, "Patch notes posted", notes[:512], discord.Color.yellow())
        await self.send_log(interaction.guild, log)

    # ── Bug group ──────────────────────────────────────────────────────────────

    bug_group = app_commands.Group(name="bug", description="Bug report commands.")

    @bug_group.command(name="report", description="Submit a bug report.")
    @app_commands.describe(description="Describe the bug")
    async def bug_report(self, interaction: discord.Interaction, description: str):
        gid = str(interaction.guild.id)
        bugs.setdefault(gid, {})
        bid = self.next_id(bugs, gid)
        entry = {
            "id": bid, "description": description,
            "reporter": str(interaction.user), "reporter_id": interaction.user.id,
            "status": "open", "created_at": datetime.now(timezone.utc).isoformat(),
        }
        bugs[gid][str(bid)] = entry
        self.save()
        embed = discord.Embed(title=f"🐛 Bug Report #{bid}", description=description, color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Status", value="🔴 Open")
        embed.set_footer(text=f"Reported by {interaction.user.display_name}")
        ch = discord.utils.get(interaction.guild.text_channels, name=BUG_REPORTS_CHANNEL)
        if ch and ch.id != interaction.channel.id:
            await ch.send(embed=embed)
        await interaction.response.send_message(f"✅ Bug **#{bid}** filed.", embed=embed)
        log = self.action_log_embed(interaction.user, f"Bug #{bid} reported", description[:256], discord.Color.red())
        await self.send_log(interaction.guild, log)

    @bug_group.command(name="list", description="List bug reports filtered by status.")
    @app_commands.describe(status="Filter: open, wip, closed, all")
    @app_commands.choices(status=[
        app_commands.Choice(name="Open",   value="open"),
        app_commands.Choice(name="In progress", value="wip"),
        app_commands.Choice(name="Closed", value="closed"),
        app_commands.Choice(name="All",    value="all"),
    ])
    async def bug_list(self, interaction: discord.Interaction, status: str = "open"):
        gid = str(interaction.guild.id)
        filtered = [b for b in bugs.get(gid, {}).values() if status == "all" or b["status"] == status]
        if not filtered:
            return await interaction.response.send_message(f"No bug reports with status **{status}**.", ephemeral=True)
        icons = {"open": "🔴", "wip": "🟡", "closed": "🟢"}
        embed = discord.Embed(title=f"🐛 Bug Reports — {status.capitalize()} ({len(filtered)})", color=discord.Color.red())
        for b in sorted(filtered, key=lambda x: x["id"])[:15]:
            desc = b["description"][:60] + ("…" if len(b["description"]) > 60 else "")
            embed.add_field(name=f"{icons.get(b['status'],'⚪')} #{b['id']} — {desc}", value=f"Reported by {b['reporter']}", inline=False)
        await interaction.response.send_message(embed=embed)

    @bug_group.command(name="view", description="View a specific bug report.")
    @app_commands.describe(bug_id="Bug report ID number")
    async def bug_view(self, interaction: discord.Interaction, bug_id: int):
        entry = bugs.get(str(interaction.guild.id), {}).get(str(bug_id))
        if not entry:
            return await interaction.response.send_message(f"❌ Bug #{bug_id} not found.", ephemeral=True)
        icons = {"open": "🔴 Open", "wip": "🟡 In Progress", "closed": "🟢 Closed"}
        embed = discord.Embed(title=f"🐛 Bug #{entry['id']}", description=entry["description"], color=discord.Color.red())
        embed.add_field(name="Status",   value=icons.get(entry["status"], entry["status"]))
        embed.add_field(name="Reporter", value=entry["reporter"])
        embed.add_field(name="Filed",    value=entry["created_at"][:10], inline=False)
        await interaction.response.send_message(embed=embed)

    @bug_group.command(name="status", description="Update a bug report's status.")
    @app_commands.describe(bug_id="Bug report ID", new_status="New status")
    @app_commands.choices(new_status=[
        app_commands.Choice(name="Open",        value="open"),
        app_commands.Choice(name="In progress", value="wip"),
        app_commands.Choice(name="Closed",      value="closed"),
    ])
    @is_dev()
    async def bug_status(self, interaction: discord.Interaction, bug_id: int, new_status: str):
        gid = str(interaction.guild.id)
        entry = bugs.get(gid, {}).get(str(bug_id))
        if not entry:
            return await interaction.response.send_message(f"❌ Bug #{bug_id} not found.", ephemeral=True)
        old = entry["status"]
        entry["status"] = new_status
        self.save()
        icons = {"open": "🔴", "wip": "🟡", "closed": "🟢"}
        await interaction.response.send_message(f"{icons[new_status]} Bug **#{bug_id}** marked as **{new_status}**.")
        log = self.action_log_embed(interaction.user, f"Bug #{bug_id} status changed", f"`{old}` → `{new_status}`", discord.Color.orange())
        await self.send_log(interaction.guild, log)

    @bug_group.command(name="close", description="Shortcut to close a bug report.")
    @app_commands.describe(bug_id="Bug report ID to close")
    @is_dev()
    async def bug_close(self, interaction: discord.Interaction, bug_id: int):
        gid = str(interaction.guild.id)
        entry = bugs.get(gid, {}).get(str(bug_id))
        if not entry:
            return await interaction.response.send_message(f"❌ Bug #{bug_id} not found.", ephemeral=True)
        entry["status"] = "closed"
        self.save()
        await interaction.response.send_message(f"🟢 Bug **#{bug_id}** closed.")
        log = self.action_log_embed(interaction.user, f"Bug #{bug_id} closed", entry["description"][:128], discord.Color.green())
        await self.send_log(interaction.guild, log)

    # ── Task group ─────────────────────────────────────────────────────────────

    task_group = app_commands.Group(name="task", description="Dev task board commands.")

    @task_group.command(name="add", description="Add a task to the board.")
    @app_commands.describe(title="Task title")
    @is_dev()
    async def task_add(self, interaction: discord.Interaction, title: str):
        gid = str(interaction.guild.id)
        tasks.setdefault(gid, {})
        tid = self.next_id(tasks, gid)
        tasks[gid][str(tid)] = {
            "id": tid, "title": title, "status": "todo",
            "assignee": None, "assignee_id": None,
            "created_by": str(interaction.user),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save()
        await interaction.response.send_message(f"✅ Task **#{tid}** added: {title}")
        await self._post_board(interaction.guild)
        log = self.action_log_embed(interaction.user, f"Task #{tid} added", title, discord.Color.blurple())
        await self.send_log(interaction.guild, log)

    @task_group.command(name="list", description="Show the current task board.")
    async def task_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._post_board(interaction.guild, interaction.channel)
        await interaction.followup.send("✅ Board posted.", ephemeral=True)

    @task_group.command(name="done", description="Mark a task as done.")
    @app_commands.describe(task_id="Task ID number")
    @is_dev()
    async def task_done(self, interaction: discord.Interaction, task_id: int):
        entry = tasks.get(str(interaction.guild.id), {}).get(str(task_id))
        if not entry:
            return await interaction.response.send_message(f"❌ Task #{task_id} not found.", ephemeral=True)
        entry["status"] = "done"
        self.save()
        await interaction.response.send_message(f"✅ Task **#{task_id}** marked as done.")
        await self._post_board(interaction.guild)
        log = self.action_log_embed(interaction.user, f"Task #{task_id} marked done", entry["title"], discord.Color.green())
        await self.send_log(interaction.guild, log)

    @task_group.command(name="wip", description="Mark a task as in progress.")
    @app_commands.describe(task_id="Task ID number")
    @is_dev()
    async def task_wip(self, interaction: discord.Interaction, task_id: int):
        entry = tasks.get(str(interaction.guild.id), {}).get(str(task_id))
        if not entry:
            return await interaction.response.send_message(f"❌ Task #{task_id} not found.", ephemeral=True)
        entry["status"] = "wip"
        self.save()
        await interaction.response.send_message(f"🟡 Task **#{task_id}** marked as in progress.")
        await self._post_board(interaction.guild)
        log = self.action_log_embed(interaction.user, f"Task #{task_id} marked in progress", entry["title"], discord.Color.yellow())
        await self.send_log(interaction.guild, log)

    @task_group.command(name="assign", description="Assign a task to a member.")
    @app_commands.describe(task_id="Task ID", member="Member to assign")
    @is_dev()
    async def task_assign(self, interaction: discord.Interaction, task_id: int, member: discord.Member):
        entry = tasks.get(str(interaction.guild.id), {}).get(str(task_id))
        if not entry:
            return await interaction.response.send_message(f"❌ Task #{task_id} not found.", ephemeral=True)
        entry["assignee"] = str(member)
        entry["assignee_id"] = member.id
        self.save()
        await interaction.response.send_message(f"📌 Task **#{task_id}** assigned to {member.mention}.")
        await self._post_board(interaction.guild)
        log = self.action_log_embed(interaction.user, f"Task #{task_id} assigned", f"Assigned to {member} — {entry['title']}", discord.Color.blurple())
        await self.send_log(interaction.guild, log)

    @task_group.command(name="delete", description="Delete a task from the board.")
    @app_commands.describe(task_id="Task ID to delete")
    @is_dev()
    async def task_delete(self, interaction: discord.Interaction, task_id: int):
        gid = str(interaction.guild.id)
        entry = tasks.get(gid, {}).pop(str(task_id), None)
        if entry is None:
            return await interaction.response.send_message(f"❌ Task #{task_id} not found.", ephemeral=True)
        self.save()
        await interaction.response.send_message(f"🗑️ Task **#{task_id}** deleted.")
        await self._post_board(interaction.guild)
        log = self.action_log_embed(interaction.user, f"Task #{task_id} deleted", entry["title"], discord.Color.red())
        await self.send_log(interaction.guild, log)

    async def _post_board(self, guild: discord.Guild, channel: discord.TextChannel = None):
        channel = channel or discord.utils.get(guild.text_channels, name=TASK_BOARD_CHANNEL)
        if not channel:
            return
        gid = str(guild.id)
        all_tasks = tasks.get(gid, {}).values()
        todo = [t for t in all_tasks if t["status"] == "todo"]
        wip  = [t for t in all_tasks if t["status"] == "wip"]
        done = [t for t in all_tasks if t["status"] == "done"]
        def fmt(lst):
            if not lst:
                return "*None*"
            lines = []
            for t in sorted(lst, key=lambda x: x["id"]):
                assignee = f" — <@{t['assignee_id']}>" if t["assignee_id"] else ""
                lines.append(f"`#{t['id']}` {t['title']}{assignee}")
            return "\n".join(lines)
        embed = discord.Embed(title="📋 Dev Task Board", color=discord.Color.blurple(), timestamp=datetime.now(timezone.utc))
        embed.add_field(name=f"📝 To Do ({len(todo)})",      value=fmt(todo), inline=False)
        embed.add_field(name=f"🔨 In Progress ({len(wip)})", value=fmt(wip),  inline=False)
        embed.add_field(name=f"✅ Done ({len(done)})",       value=fmt(done), inline=False)
        embed.set_footer(text="Use /task commands to manage")
        await channel.send(embed=embed)

    async def cog_load(self):
        self.bot.tree.add_command(self.update_group)
        self.bot.tree.add_command(self.bug_group)
        self.bot.tree.add_command(self.task_group)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        else:
            raise error

async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
