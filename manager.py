
import discord
from discord.ext import commands
import os
import json
from pathlib import Path

# -------------------- Configuration --------------------
PREFIX = "?"
WARN_FILE = Path("warns.json")
TOKEN = os.getenv("DISCORD_TOKEN") or "YOUR_BOT_TOKEN_HERE"
# -------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # required for on_member_join and member operations

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# -------------------- Helpers --------------------

def load_warns():
    if WARN_FILE.exists():
        return json.loads(WARN_FILE.read_text(encoding="utf-8"))
    return {}


def save_warns(data):
    WARN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


async def get_or_create_channel(guild: discord.Guild, name: str, *, category=None):
    for ch in guild.text_channels:
        if ch.name == name:
            return ch
    return await guild.create_text_channel(name, category=category)


async def log_action(guild: discord.Guild, message: str):
    ch = discord.utils.get(guild.text_channels, name="mod-log")
    if ch is None:
        try:
            ch = await guild.create_text_channel("mod-log")
        except Exception:
            return
    await ch.send(message)


# -------------------- Events --------------------

@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user} (guilds: {len(bot.guilds)})")


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    welcome_channel = discord.utils.get(guild.text_channels, name="welcome")
    if welcome_channel is None:
        # don't create flood — only create if necessary
        try:
            welcome_channel = await guild.create_text_channel("welcome")
        except Exception:
            return
    await welcome_channel.send(f"Welcome {member.mention}! Say hi 👋")


# -------------------- Basic Commands --------------------

@bot.command(name="ping")
async def ping(ctx):
    """Check bot latency"""
    await ctx.send(f"Pong! {round(bot.latency*1000)}ms")


@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(title="Help — Commands", color=discord.Color.blurple())
    embed.add_field(name="Moderation", value="?kick @user [reason]\n?ban @user [reason]\n?unban user#1234", inline=False)
    embed.add_field(name="Utility", value="?clear <num>\n?userinfo @user\n?serverinfo", inline=False)
    embed.add_field(name="Role/Lock", value="?mute @user\n?unmute @user\n?lock\n?unlock", inline=False)
    embed.set_footer(text="Prefix: ?")
    await ctx.send(embed=embed)


# -------------------- Moderation --------------------

def mod_check(ctx):
    return ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.kick_members


@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.kick(reason=reason)
        await ctx.send(f"✅ Kicked {member} — {reason}")
        await log_action(ctx.guild, f"{ctx.author} kicked {member} — {reason}")
    except Exception as e:
        await ctx.send(f"❌ Could not kick: {e}")


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.ban(reason=reason)
        await ctx.send(f"✅ Banned {member} — {reason}")
        await log_action(ctx.guild, f"{ctx.author} banned {member} — {reason}")
    except Exception as e:
        await ctx.send(f"❌ Could not ban: {e}")


@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, member: str):
    # member should be name#discrim
    banned = await ctx.guild.bans()
    name, discrim = member.split("#")
    for entry in banned:
        user = entry.user
        if (user.name, user.discriminator) == (name, discrim):
            await ctx.guild.unban(user)
            await ctx.send(f"✅ Unbanned {user}")
            await log_action(ctx.guild, f"{ctx.author} unbanned {user}")
            return
    await ctx.send("❌ User not found in ban list")


@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    if amount > 100:
        await ctx.send("Can only delete up to 100 messages at a time")
        return
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"🧹 Deleted {len(deleted)} messages", delete_after=5)
    await log_action(ctx.guild, f"{ctx.author} cleared {len(deleted)} messages in #{ctx.channel.name}")


# -------------------- Mute --------------------

async def ensure_muted_role(guild: discord.Guild):
    role = discord.utils.get(guild.roles, name="Muted")
    if role is None:
        role = await guild.create_role(name="Muted", reason="Needed for muting members")
        for ch in guild.channels:
            try:
                await ch.set_permissions(role, send_messages=False, speak=False)
            except Exception:
                pass
    return role


@bot.command(name="mute")
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    role = await ensure_muted_role(ctx.guild)
    await member.add_roles(role, reason=reason)
    await ctx.send(f"🔇 Muted {member}")
    await log_action(ctx.guild, f"{ctx.author} muted {member} — {reason}")


@bot.command(name="unmute")
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")
    if role in member.roles:
        await member.remove_roles(role)
        await ctx.send(f"🔊 Unmuted {member}")
        await log_action(ctx.guild, f"{ctx.author} unmuted {member}")
    else:
        await ctx.send("User is not muted")


# -------------------- Warns --------------------

@bot.command(name="warn")
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    data = load_warns()
    gid = str(ctx.guild.id)
    data.setdefault(gid, {})
    user_warns = data[gid].setdefault(str(member.id), [])
    user_warns.append({"by": str(ctx.author.id), "reason": reason})
    save_warns(data)
    await ctx.send(f"⚠️ Warned {member}: {reason}")
    await log_action(ctx.guild, f"{ctx.author} warned {member} — {reason}")


@bot.command(name="warns")
@commands.has_permissions(manage_messages=True)
async def warns(ctx, member: discord.Member = None):
    data = load_warns()
    gid = str(ctx.guild.id)
    if member is None:
        member = ctx.author
    user_warns = data.get(gid, {}).get(str(member.id), [])
    if not user_warns:
        await ctx.send(f"No warns for {member}")
        return
    embed = discord.Embed(title=f"Warns for {member}")
    for i, w in enumerate(user_warns, 1):
        by_member = ctx.guild.get_member(int(w["by"]))
        embed.add_field(name=f"#{i}", value=f"By: {by_member or w['by']} — {w['reason']}", inline=False)
    await ctx.send(embed=embed)


# -------------------- Roles & Channel Lock --------------------

@bot.command(name="create_role")
@commands.has_permissions(manage_roles=True)
async def create_role(ctx, name: str):
    try:
        role = await ctx.guild.create_role(name=name)
        await ctx.send(f"✅ Created role {role.name}")
    except Exception as e:
        await ctx.send(f"❌ Could not create role: {e}")


@bot.command(name="give_role")
@commands.has_permissions(manage_roles=True)
async def give_role(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.add_roles(role)
        await ctx.send(f"✅ Given {role.name} to {member.display_name}")
    except Exception as e:
        await ctx.send(f"❌ {e}")


@bot.command(name="remove_role")
@commands.has_permissions(manage_roles=True)
async def remove_role(ctx, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role)
        await ctx.send(f"✅ Removed {role.name} from {member.display_name}")
    except Exception as e:
        await ctx.send(f"❌ {e}")


@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
async def lock(ctx):
    ch = ctx.channel
    await ch.set_permissions(ctx.guild.default_role, send_messages=False)
    await ctx.send("🔐 Channel locked")
    await log_action(ctx.guild, f"{ctx.author} locked #{ch.name}")


@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    ch = ctx.channel
    await ch.set_permissions(ctx.guild.default_role, send_messages=None)
    await ctx.send("🔓 Channel unlocked")
    await log_action(ctx.guild, f"{ctx.author} unlocked #{ch.name}")


# -------------------- Info Commands --------------------

@bot.command(name="userinfo")
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    embed = discord.Embed(title=str(member), description=f"ID: {member.id}")
    embed.add_field(name="Joined", value=member.joined_at)
    embed.add_field(name="Created", value=member.created_at)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="serverinfo")
async def serverinfo(ctx):
    g = ctx.guild
    embed = discord.Embed(title=g.name)
    embed.add_field(name="Members", value=g.member_count)
    embed.add_field(name="Owner", value=str(g.owner))
    embed.set_thumbnail(url=g.icon.url if g.icon else discord.Embed.Empty)
    await ctx.send(embed=embed)


# -------------------- Error Handling --------------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You do not have permission to run that command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing argument. Check your command usage.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Bad argument. Make sure you mentioned roles/members correctly.")
    else:
        # Unhandled errors — print to console and send minimal user message
        print("Error:", error)
        await ctx.send("❌ An error occurred. Check console for details.")


# -------------------- Run --------------------

if __name__ == "__main__":
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("Warning: You didn't set a token. Put it into the DISCORD_TOKEN environment variable or edit the file.")
    bot.run(TOKEN)
