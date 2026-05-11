import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import json
import os

# ── Configuration ──────────────────────────────────────────────────────────────

# Channel where the agree button is posted
AGREE_CHANNEL_ID = 1503142618970980403

# Role granted after agreeing
VERIFIED_ROLE_ID = 1502942391341158491

LOG_CHANNEL_NAME = "mod-log"

DATA_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")
AGREED_FILE   = os.path.join(DATA_DIR, "marketplace_agreed.json")

# ── Today's date ───────────────────────────────────────────────────────────────
TODAY = "May 10, 2025"

# ── Document text ──────────────────────────────────────────────────────────────

TOS_TEXT = f"""**Cloggy Marketplace – Terms of Service**
*Last Updated: {TODAY}*

These Terms of Service ("Terms") govern your access to and use of the Cloggy Marketplace ("Marketplace"), operated through our Discord server and any associated platforms. By accessing, purchasing from, or participating in the Marketplace, you agree to be bound by these Terms.

**1. Definitions**
"Marketplace" refers to the Discord server and any associated channels where digital products are listed, sold, or distributed. "Products" refers to all digital goods sold or distributed. "License" refers to the limited rights granted to you to use Products under these Terms.

**2. License Grant**
When you purchase a Product, you are purchasing a non-exclusive, non-transferable, revocable license to use the Product for your own personal or commercial projects. You do not gain any intellectual property rights, copyright ownership, or distribution rights.

**3. Restrictions on Use**
Unless you have obtained a separate written resale license, you may not resell, redistribute, repackage, share, upload to any asset library, claim ownership of, or modify and distribute any Product.

**4. Resale Licensing**
Reselling or redistributing Products is strictly prohibited unless you have obtained a formal resale license issued directly by us. A resale license must be explicitly granted, documented, and may be revoked at our discretion.

**5. Refund Policy**
Due to the nature of digital goods, all sales are final. We do not offer refunds, exchanges, or returns unless required by applicable law.

**6. Marketplace Conduct**
Users must follow Discord's Terms of Service, and must not engage in harassment, scams, fraudulent activity, payment bypass attempts, or impersonation of staff or verified sellers.

**7. Intellectual Property**
All Products remain the intellectual property of their original creators or licensors. You may not claim ownership, authorship, or exclusive rights to any Product.

**8. Termination of Access**
We may suspend or terminate your access at any time, with or without cause, including for violation of these Terms, attempted resale without a license, fraudulent activity, or abuse of staff or users. Termination does not entitle you to a refund.

**9. Disclaimer of Warranties**
All Products are provided "as is" without warranties of any kind. We do not guarantee compatibility, performance, or suitability for any specific purpose.

**10. Limitation of Liability**
To the fullest extent permitted by law, we are not liable for loss of data, loss of profits, damages arising from use of Products, or issues caused by third-party platforms. Your use of the Marketplace is at your own risk.

**11. Governing Law**
These Terms are governed by the laws of the United States and Australia, depending on jurisdictional applicability.

**12. Changes to Terms**
We reserve the right to modify these Terms at any time without prior notice. Continued use constitutes acceptance of updated Terms."""

DMCA_TEXT = f"""**Cloggy Marketplace – DMCA Policy**
*Last Updated: {TODAY}*

This DMCA Policy describes how Cloggy Marketplace handles copyright infringement claims in accordance with the Digital Millennium Copyright Act (DMCA), 17 U.S.C. § 512.

**1. Scope**
This policy applies to all digital products distributed through the Marketplace, including 3D models, game assets, maps, textures, scripts, animations, and any other digital content sold or shared within the Marketplace.

**2. Reporting Copyright Infringement (Takedown Notice)**
If you believe your copyrighted work has been infringed, your notice must include: identification of the copyrighted work; identification of the infringing material (links, usernames, message IDs, or screenshots); your full legal name and contact information; a good-faith belief statement; a statement under penalty of perjury that the information is accurate and you are the copyright owner or authorized agent; and your physical or electronic signature.

Send notices to Marketplace administrators through the designated Discord contact channel. Incomplete notices may be rejected.

**3. Removal of Content**
Upon receiving a valid takedown notice, we will remove or disable access to the allegedly infringing content, may notify the user who posted it, and may restrict or terminate that user's access. We reserve the right to remove content without prior notice.

**4. Counter-Notification**
If you believe your content was removed in error, your counter-notification must include: identification of the removed material and its prior location; your full legal name and contact information; a statement under penalty of perjury that removal was due to mistake or misidentification; consent to jurisdiction of the courts in your region; and your physical or electronic signature.

If valid, we may restore the content unless the complainant files legal action within 10–14 business days.

**5. Repeat Infringer Policy**
Users who repeatedly violate copyright laws or this policy may have their access permanently terminated. We reserve the right to determine what constitutes a repeat infringer.

**6. Marketplace Licensing Reminder**
All purchases are licenses, not ownership transfers. Unauthorized redistribution, resale, or re-uploading of any product is strictly prohibited unless you hold a formal resale license. Violations may result in DMCA action and removal from the Marketplace.

**7. No Legal Advice**
Nothing in this policy constitutes legal advice. If you are unsure about your rights or obligations, consult an attorney.

**8. Policy Changes**
We reserve the right to modify this policy at any time without prior notice. Continued use of the Marketplace constitutes acceptance of any updated policy."""

# ── Persistence ────────────────────────────────────────────────────────────────

def load_agreed() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(AGREED_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_agreed(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(AGREED_FILE, "w") as f:
        json.dump(data, f, indent=2)

agreed_data: dict = {}

# ── Views ──────────────────────────────────────────────────────────────────────


def chunk_text(text: str, limit: int = 1900) -> list[str]:
    """Split text into chunks that fit within Discord's message limit."""
    lines   = text.split("\n")
    chunks  = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current.strip())
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        chunks.append(current.strip())
    return chunks

async def send_long_dm(user: discord.User, intro: str, body: str, view: discord.ui.View = None):
    """Send a long document as multiple DM messages, attaching the view to the last one."""
    chunks = chunk_text(body)
    await user.send(intro)
    for i, chunk in enumerate(chunks):
        is_last = i == len(chunks) - 1
        await user.send(chunk, view=view if is_last else None)


class AgreementView(discord.ui.View):
    """Persistent view with the 'Read & Agree' button posted in the agree channel."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📜 Read & Agree to Terms",
        style=discord.ButtonStyle.blurple,
        custom_id="marketplace:start_agreement"
    )
    async def start_agreement(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check if already agreed
        if str(interaction.user.id) in agreed_data.get(str(interaction.guild.id), {}):
            return await interaction.response.send_message(
                "✅ You've already agreed to the Marketplace Terms and DMCA Policy.",
                ephemeral=True
            )
        # Send ToS via DM first
        try:
            await interaction.user.send(
                "📋 **Please read the Cloggy Marketplace Terms of Service below.**\n"
                "You must agree to both this and the DMCA Policy to access the Marketplace.\n\n"
                + TOS_TEXT,
                view=TosAgreeView(interaction.guild.id, interaction.user.id)
            )
            await interaction.response.send_message(
                "📬 Check your DMs! The Terms of Service has been sent to you.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't DM you. Please enable DMs from server members in your Privacy Settings and try again.",
                ephemeral=True
            )


class TosAgreeView(discord.ui.View):
    """Sent in DMs — user agrees to ToS, then gets sent the DMCA."""

    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user_id  = user_id

    @discord.ui.button(label="✅ I agree to the Terms of Service", style=discord.ButtonStyle.green)
    async def agree_tos(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.send_message("✅ Terms of Service accepted.")
        await send_long_dm(
            interaction.user,
            "📋 **Now please read the DMCA Policy below.**",
            DMCA_TEXT,
            view=DmcaAgreeView(self.guild_id, self.user_id)
        )

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red)
    async def decline_tos(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="❌ You have declined the Terms of Service. You will not be granted Marketplace access.",
            view=None
        )


class DmcaAgreeView(discord.ui.View):
    """Sent in DMs after ToS — user agrees to DMCA to complete verification."""

    def __init__(self, guild_id: int, user_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user_id  = user_id

    @discord.ui.button(label="✅ I agree to the DMCA Policy", style=discord.ButtonStyle.green)
    async def agree_dmca(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        await interaction.message.edit(view=self)

        # Record agreement
        agreed_data.setdefault(str(self.guild_id), {})[str(self.user_id)] = {
            "agreed_at": datetime.now(timezone.utc).isoformat(),
            "user_tag":  str(interaction.user),
        }
        save_agreed(agreed_data)

        # Grant role
        guild  = interaction.client.get_guild(self.guild_id)
        role   = guild.get_role(VERIFIED_ROLE_ID) if guild else None
        member = guild.get_member(self.user_id) if guild else None

        if member and role:
            try:
                await member.add_roles(role, reason="Agreed to Marketplace ToS and DMCA Policy")
            except discord.Forbidden:
                pass

        # Log to mod-log
        if guild:
            log_ch = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
            if log_ch:
                embed = discord.Embed(
                    title="📋 Marketplace Agreement",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="User", value=f"{interaction.user.mention} (`{interaction.user.id}`)")
                embed.add_field(name="Agreed to", value="Terms of Service + DMCA Policy")
                embed.add_field(name="Role Granted", value=role.mention if role else f"`{VERIFIED_ROLE_ID}`")
                await log_ch.send(embed=embed)

        await interaction.response.send_message(
            "🎉 **You're all set!**\n"
            "You have agreed to both the Terms of Service and DMCA Policy.\n"
            f"You've been granted access to the Cloggy Marketplace. Welcome!"
        )

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.red)
    async def decline_dmca(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="❌ You have declined the DMCA Policy. You will not be granted Marketplace access.",
            view=None
        )


# ── Cog ────────────────────────────────────────────────────────────────────────

class Marketplace(commands.Cog):
    """Marketplace agreement system — ToS and DMCA acknowledgement."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        global agreed_data
        agreed_data = load_agreed()
        # Re-register persistent view so the button works after restarts
        self.bot.add_view(AgreementView())

    @app_commands.command(name="marketplace_setup", description="Post the Marketplace agreement button in the configured channel. Run once.")
    @app_commands.default_permissions(administrator=True)
    async def marketplace_setup(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(AGREE_CHANNEL_ID)
        if not channel:
            return await interaction.response.send_message(
                f"❌ Could not find channel `{AGREE_CHANNEL_ID}`. Check the ID in marketplace.py.",
                ephemeral=True
            )
        embed = discord.Embed(
            title="📋 Cloggy Marketplace Access",
            description=(
                "To gain access to the Marketplace you must read and agree to both:\n\n"
                "• **Terms of Service**\n"
                "• **DMCA Policy**\n\n"
                "Click the button below and follow the steps sent to your DMs.\n\n"
                "⚠️ Make sure your DMs are open from server members before clicking."
            ),
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Last updated: {TODAY}")
        await channel.send(embed=embed, view=AgreementView())
        await interaction.response.send_message(
            f"✅ Agreement button posted in {channel.mention}.", ephemeral=True
        )

    @app_commands.command(name="marketplace_revoke", description="Revoke a user's Marketplace agreement and role.")
    @app_commands.describe(member="Member to revoke access from", reason="Reason")
    @app_commands.default_permissions(administrator=True)
    async def marketplace_revoke(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        # Remove from agreed data
        agreed_data.get(str(interaction.guild.id), {}).pop(str(member.id), None)
        save_agreed(agreed_data)

        # Remove role
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if role and role in member.roles:
            await member.remove_roles(role, reason=f"Marketplace access revoked by {interaction.user}: {reason}")

        await interaction.response.send_message(
            f"✅ Revoked Marketplace access for {member.mention}.", ephemeral=True
        )

        log_ch = discord.utils.get(interaction.guild.text_channels, name=LOG_CHANNEL_NAME)
        if log_ch:
            embed = discord.Embed(title="📋 Marketplace Access Revoked", color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
            embed.add_field(name="User",        value=f"{member.mention} (`{member.id}`)")
            embed.add_field(name="Revoked by",  value=interaction.user.mention)
            embed.add_field(name="Reason",      value=reason, inline=False)
            await log_ch.send(embed=embed)

        try:
            await member.send(
                f"⚠️ Your access to the **Cloggy Marketplace** has been revoked.\nReason: {reason}"
            )
        except discord.Forbidden:
            pass

    @app_commands.command(name="marketplace_check", description="Check if a member has agreed to the Marketplace terms.")
    @app_commands.describe(member="Member to check")
    @app_commands.default_permissions(manage_guild=True)
    async def marketplace_check(self, interaction: discord.Interaction, member: discord.Member):
        entry = agreed_data.get(str(interaction.guild.id), {}).get(str(member.id))
        if entry:
            embed = discord.Embed(title="📋 Marketplace Agreement Status", color=discord.Color.green())
            embed.add_field(name="User",      value=member.mention)
            embed.add_field(name="Status",    value="✅ Agreed")
            embed.add_field(name="Agreed at", value=entry.get("agreed_at", "Unknown")[:10], inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(
                f"❌ {member.mention} has not agreed to the Marketplace terms.",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Marketplace(bot))
