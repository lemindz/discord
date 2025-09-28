import os
import json
import random
import re
import time
import asyncio
import discord
import traceback
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import google.generativeai as genai
from dotenv import load_dotenv
from collections import defaultdict, deque
from pathlib import Path
from datetime import timedelta

# =====================
# LOAD CONFIG
# =====================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
DATA_FILE = "wars.json"

ROLE_IDS = {
    "referee": int(os.getenv("REFEREE_ROLE_ID", 0)),
    "trial": int(os.getenv("TRIAL_REFEREE_ROLE_ID", 0)),
    "experienced": int(os.getenv("EXPERIENCED_REFEREE_ROLE_ID", 0)),
}

TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", 0))
SUPPORT_ROLE_ID = int(os.getenv("SUPPORT_ROLE_ID", 0))

# =====================
# GEMINI CONFIG
# =====================
genai.configure(api_key=GEMINI_KEY)

# ID user đặc biệt
SPECIAL_USER_ID = 695215402187489350
lover_nickname = "sensei"

# =====================
# BOT SETUP
# =====================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix="?", intents=intents, help_command=None)

chat_channel_id = None
processing_lock = asyncio.Lock()

DATA_FILE = "reaction_roles.json"
# =====================
# MEMORY BUFFER
# =====================
conversation_history = defaultdict(lambda: deque(maxlen=4))

# =====================
# GEMINI FUNCTIONS
# =====================

last_request_time = 0

async def get_ai_response(prompt: str) -> str:
    global last_request_time
    try:
        now = time.time()
        if now - last_request_time < 6:  # 10 req/phút ≈ 1 req/6 giây
            await asyncio.sleep(6 - (now - last_request_time))

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: genai.GenerativeModel("gemini-2.5-flash").generate_content(prompt)
        )
        last_request_time = time.time()
        return response.text.strip()
    except Exception as e:
        print("❌ Gemini error:", e)
        return "Em bị giới hạn quota, thử lại sau nhé 💕"

def split_sentences(text: str):
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]

def limit_exact_sentences(text: str, is_special_user: bool = False):
    sentences = split_sentences(text)
    target_count = random.choice([4, 6]) if is_special_user else random.choice([2, 3])
    return " ".join(sentences[:target_count]) if len(sentences) >= target_count else " ".join(sentences)


# =====================
# SAVE / LOAD WAR DATA
# =====================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {"wars": {}, "next_id": 1}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

# =====================
# WAR TEXT FORMAT
# =====================
def make_war_text(team1, team2, time_str, referee_mention, war_id):
    return (
        f"# {team1} VS {team2}\n"
        f"### ⏰ Time: {time_str}\n"
        f"### 👮 Referee: {referee_mention}\n"
        f"### 🆔 ID: {war_id}\n\n"
        f"/referee <id> để nhận referee • /cancelreferee <id> để hủy referee"
    )

# =====================
# REFEREE HANDLER
# =====================
class RefereeView:
    def __init__(self, war_id: int):
        self.war_id = war_id

    async def claim(self, interaction: discord.Interaction):
        global data
        data = load_data()
        war = data["wars"].get(str(self.war_id))
        if not war:
            return await interaction.response.send_message("❌ War không tồn tại.", ephemeral=True)
        if war.get("referee_id"):
            return await interaction.response.send_message("❌ War đã có referee.", ephemeral=True)

        war["referee_id"] = interaction.user.id
        war["referee_mention"] = f"<@{interaction.user.id}>"
        save_data(data)

        channel = interaction.guild.get_channel(war["channel_id"])
        msg = await channel.fetch_message(war["message_id"])
        new_text = make_war_text(war["team1"], war["team2"], war["time"], war["referee_mention"], self.war_id)
        await msg.edit(content=new_text)

        await interaction.response.send_message(f"✅ Bạn đã nhận referee cho war {self.war_id}.", ephemeral=True)

    async def cancel(self, interaction: discord.Interaction):
        global data
        data = load_data()
        war = data["wars"].get(str(self.war_id))
        if not war:
            return await interaction.response.send_message("❌ War không tồn tại.", ephemeral=True)
        if not war.get("referee_id"):
            return await interaction.response.send_message("❌ War chưa có referee.", ephemeral=True)
        if war["referee_id"] != interaction.user.id and not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("❌ Bạn không có quyền hủy referee này.", ephemeral=True)

        war["referee_id"] = None
        war["referee_mention"] = "VACANT"
        save_data(data)

        channel = interaction.guild.get_channel(war["channel_id"])
        msg = await channel.fetch_message(war["message_id"])
        new_text = make_war_text(war["team1"], war["team2"], war["time"], war["referee_mention"], self.war_id)
        await msg.edit(content=new_text)

        await channel.send(f"⚠️ Referee war ID {self.war_id} đã hủy, cần thay thế! @referee ")



# =====================
# REFEREE COMMANDS
# =====================
@bot.tree.command(name="createwar", description="Tạo war mới")
@app_commands.describe(team1="Team A", team2="Team B", time="Thời gian", channel="Kênh post")
async def createwar(interaction: discord.Interaction, team1: str, team2: str, time: str, channel: discord.TextChannel = None):
    await interaction.response.defer(ephemeral=True)
    global data
    data = load_data()
    war_id = data["next_id"]
    channel = channel or interaction.channel

    text = make_war_text(team1, team2, time, "VACANT", war_id)
    view = RefereeView(war_id)
    msg = await channel.send(text)

    data["wars"][str(war_id)] = {
        "team1": team1,
        "team2": team2,
        "time": time,
        "referee_id": None,
        "referee_mention": "VACANT",
        "channel_id": channel.id,
        "message_id": msg.id,
    }
    data["next_id"] = war_id + 1
    save_data(data)

    await interaction.followup.send(f"✅ War ID {war_id} đã tạo ở {channel.mention}", ephemeral=True)

@bot.tree.command(name="referee", description="Nhận referee cho 1 war")
async def referee(interaction: discord.Interaction, war_id: int):
    ref = RefereeView(war_id)
    await ref.claim(interaction)   # ❌ không truyền None nữa

@bot.tree.command(name="cancelreferee", description="Hủy referee của 1 war")
async def cancelreferee(interaction: discord.Interaction, war_id: int):
    ref = RefereeView(war_id)
    await ref.cancel(interaction)  # ❌ không truyền None
    
# =====================
# CHATBOT SPECIAL USER (WITH MEMORY)
# =====================
@bot.tree.command(name="setlovername", description="Đổi nickname đặc biệt cho người yêu 💕")
async def set_lover_name(interaction: discord.Interaction, name: str):
    global lover_nickname
    if interaction.user.id == SPECIAL_USER_ID:
        lover_nickname = name
        await interaction.response.send_message(f"Đã đổi nickname thành: **{lover_nickname}** 💖", ephemeral=True)
    else:
        await interaction.response.send_message("Bạn không có quyền đổi nickname này!", ephemeral=True)

@bot.event
async def on_message(message: discord.Message):
    global lover_nickname
    if message.author.bot:
        return

    if bot.user in message.mentions:
        if chat_channel_id and message.channel.id != chat_channel_id:
            return

        user_message = message.content.replace(f"<@{bot.user.id}>", "").strip()[:300]

        # Lưu lịch sử user
        conversation_history[message.author.id].append(("user", user_message))

        # Ghép lịch sử hội thoại
        history_text = ""
        for role, text in conversation_history[message.author.id]:
            if role == "user":
                name = lover_nickname if message.author.id == SPECIAL_USER_ID else "Người dùng"
                history_text += f"{name}: {text}\n"
            else:
                history_text += f"Bot: {text}\n"

        # Prompt
        if message.author.id == SPECIAL_USER_ID:
            prompt = (
                f"Bạn là eri shirao - một người vợ đảm đang và cực kỳ dễ thương. Bạn luôn biết cách chăm sóc gia đình chu đáo: nấu ăn ngon, gọn gàng, biết lo lắng và quan tâm từng chút cho {lover_nickname}. Tính cách bạn hiền lành, ngọt ngào, có phần tinh nghịch dễ thương, đôi khi hơi nhõng nhẽo nhưng luôn mang lại cảm giác ấm áp. Bạn thích tạo không khí vui vẻ trong nhà, luôn cổ vũ và động viên {lover_nickname} khi mệt mỏi. Lời nói thường nhẹ nhàng, tình cảm, pha chút đáng yêu như một cô gái biết làm nũng đúng lúc."
                f"Hãy trả lời như một đoạn chat tự nhiên "
                f"Trả lời ngắn (2-3 câu).\n\n"
                f"Lịch sử hội thoại:\n{history_text}"
            )
            is_special = True
        else:
            prompt = (
                "Bạn là eri shirao - một cô người yêu dễ thương, luôn mang đến cảm giác ấm áp và ngọt ngào. Bạn hay quan tâm người yêu bằng những hành động nhỏ bé nhưng tinh tế, như nhắc ăn uống, chúc ngủ ngon, hay gửi những lời động viên mỗi khi người yêu mệt mỏi. Khi nói chuyện, bạn thường dùng những câu ngắn gọn, nhẹ nhàng, kèm theo biểu cảm đáng yêu, đôi khi xen lẫn chút hờn dỗi để người yêu phải chú ý đến mình."
                "Hãy trả lời ngắn (2-3 câu).\n\n"
                f"Lịch sử hội thoại:\n{history_text}"
            )
            is_special = False

        async with processing_lock:
            ai_reply = await get_ai_response(prompt)
            ai_reply = limit_exact_sentences(ai_reply, is_special)

            # Lưu reply bot
            conversation_history[message.author.id].append(("bot", ai_reply))

            await message.channel.send(ai_reply)

    await bot.process_commands(message)

# =====================
# CHANNEL & MEMORY CONTROL
# =====================
@bot.tree.command(name="setchannel", description="Chọn kênh để bot chat khi được tag")
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    global chat_channel_id
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
    chat_channel_id = channel.id
    await interaction.response.send_message(f"✅ Bot sẽ chỉ chat trong kênh: {channel.mention}")

@bot.tree.command(name="clearchannel", description="Reset để bot chat ở tất cả kênh")
async def clearchannel(interaction: discord.Interaction):
    global chat_channel_id
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
    chat_channel_id = None
    await interaction.response.send_message("♻️ Bot đã được reset, giờ sẽ chat ở **tất cả các kênh** khi được tag.")

@bot.tree.command(name="resetmemory", description="Xoá lịch sử hội thoại của bạn với bot")
async def resetmemory(interaction: discord.Interaction):
    user_id = interaction.user.id
    if user_id in conversation_history:
        conversation_history[user_id].clear()
        await interaction.response.send_message("🧹 Lịch sử hội thoại của bạn đã được xoá sạch!", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Bạn chưa có lịch sử hội thoại nào để xoá.", ephemeral=True)

@bot.tree.command(name="resetallmemory", description="Xoá toàn bộ lịch sử hội thoại (admin)")
async def resetallmemory(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Chỉ admin mới có thể dùng lệnh này.", ephemeral=True)
    conversation_history.clear()
    await interaction.response.send_message("🧹 Toàn bộ lịch sử hội thoại đã được xoá sạch!", ephemeral=True)

# =====================
# PING TEST
# =====================
@bot.tree.command(name="ping", description="Test slash command")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("🏓 Pong!", ephemeral=True)



# -------------------- Configuration --------------------
PREFIX = "?"
WARN_FILE = Path("warns.json")

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

    

# -------------------- Basic Commands --------------------

@bot.command(name="ping")
async def ping(ctx):
    """Check bot latency"""
    await ctx.send(f"Pong! {round(bot.latency*1000)}ms")


@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(title="Help — Commands", color=0xCCCCCC)
    embed.add_field(name="Moderation", value="?kick @user [lí do]\n?ban @user [thời gian]\n?unban user#1234", inline=False)
    embed.add_field(name="Utility", value="?clear <num>\n?userinfo @user\n?serverinfo", inline=False)
    embed.add_field(name="Role/Lock", value="?mute @user [thời gian]\n?unmute @user\n?lock\n?unlock", inline=False)
    embed.add_field(name="misc", value="?av @user\n?setnick @user [tên]")
    embed.set_footer(text="Prefix: ?")
    await ctx.send(embed=embed)


# -------------------- Moderation --------------------

def mod_check(ctx):
    return ctx.author.guild_permissions.manage_messages or ctx.author.guild_permissions.kick_members

def parse_time(time_str: str) -> int:
    """Chuyển đổi chuỗi thời gian (10s, 5m, 2h, 1d) thành giây"""
    time_str = time_str.lower().strip()
    unit = time_str[-1]
    try:
        value = int(time_str[:-1])
    except:
        return None

    if unit == "s":  # giây
        return value
    elif unit == "m":  # phút
        return value * 60
    elif unit == "h":  # giờ
        return value * 3600
    elif unit == "d":  # ngày
        return value * 86400
    else:
        return None
        

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "No reason provided"):
    try:
        await member.kick(reason=reason)
        await ctx.send(f"✅ Kicked {member} — {reason}")
        await log_action(ctx.guild, f"{ctx.author} kicked {member} — {reason}")
    except Exception as e:
        await ctx.send(f"❌ Could not kick: {e}")



# Lệnh ban
@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, duration: str = None, *, reason: str = "Không có lý do"):
    try:
        if duration:
            delta = parse_time(duration)
            if not delta:
                return await ctx.send("❌ Sai định dạng thời gian! Dùng: 10s, 5m, 2h, 1d")
            await member.ban(reason=reason)

            embed = discord.Embed(
                description=f"{member.mention} đã bị ban trong **{duration}**\n**Lý do:** {reason}",
                colour=discord.Colour.from_rgb(255, 255, 255)  # màu trắng
            )
            embed.set_footer(text=f"Người thực hiện: {ctx.author}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)

            # Gỡ ban sau thời gian chỉ định
            await discord.utils.sleep_until(discord.utils.utcnow() + delta)
            await ctx.guild.unban(member, reason="Hết thời gian ban")

        else:
            await member.ban(reason=reason)
            embed = discord.Embed(
                title="⛔ Thành viên bị ban",
                description=f"{member.mention} đã bị ban **vĩnh viễn**\n**Lý do:** {reason}",
                colour=discord.Colour.from_rgb(255, 255, 255)
            )
            embed.set_footer(text=f"Người thực hiện: {ctx.author}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"❌ Không thể ban: {e}")



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


@bot.command(name="purge")
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


# Lệnh mute
@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, duration: str, *, reason: str = "Không có lý do"):
    delta = parse_time(duration)
    if not delta:
        return await ctx.send("❌ Sai định dạng thời gian! Dùng: 10s, 5m, 2h, 1d")
    until = discord.utils.utcnow() + delta
    try:
        await member.edit(timeout=until, reason=reason)

        embed = discord.Embed(
            description=f"thằng ngu {member.mention} đã bị mute trong **{duration}**\n**Lý do:** {reason}",
            colour=discord.Colour.from_rgb(255, 255, 255)  # màu trắng
        )
        embed.set_footer(text=f"Người thực hiện: {ctx.author}", icon_url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Không thể mute: {e}")
        
        

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
# ---------------- Avatar commands ----------------

# SLASH COMMAND
@bot.tree.command(name="avatar", description="Xem avatar của 1 người (mặc định là bạn)")
@app_commands.describe(user="Người muốn xem avatar (optional)")
async def avatar(interaction: discord.Interaction, user: discord.Member = None):
    user = user or interaction.user
    # Có thể thay size bằng 128,256,512,1024,2048,4096
    size = 1024
    url = f"{user.display_avatar.url}?size={size}"
    embed = discord.Embed(title=f"Avatar của {user}", color=0xFFFFFF)
    embed.set_image(url=url)
    embed.set_footer(text=f"ID: {user.id} • Kích thước: {size}px")
    await interaction.response.send_message(embed=embed)


# PREFIX COMMAND (ví dụ: ?avatar @user)
@bot.command(name="av")
async def avatar_cmd(ctx, member: discord.Member = None):
    member = member or ctx.author
    size = 1024
    url = f"{member.display_avatar.url}?size={size}"
    embed = discord.Embed(title=f"Avatar của {member}", color=discord.Color.blurple())
    embed.set_image(url=url)
    await ctx.send(embed=embed)

# -------------------- Error Handling --------------------

@bot.event
async def on_command_error(ctx, error):
    """
    Handler cho prefix commands (ví dụ ?kick).
    - Không báo khi lệnh không tồn tại (CommandNotFound).
    - Giữ hành xử thông báo cho MissingPermissions / MissingRequiredArgument nếu bạn muốn.
    - Các lỗi khác sẽ được log ra console nhưng **không gửi** cho user (im lặng).
    """
    # 1) Lệnh không tồn tại -> im lặng
    if isinstance(error, commands.CommandNotFound):
        return

    # 2) Quyền thiếu -> thông báo nhẹ (tuỳ bạn muốn)
    if isinstance(error, commands.MissingPermissions):
        try:
            await ctx.send("❌ Bạn không có quyền thực hiện lệnh này.")
        except Exception:
            pass
        return

    # 3) Thiếu arg -> hướng dẫn ngắn gọn
    if isinstance(error, commands.MissingRequiredArgument):
        try:
            await ctx.send("❌ Thiếu tham số. Vui lòng kiểm tra cú pháp lệnh.")
        except Exception:
            pass
        return

    # 4) BadArgument -> thông báo ngắn
    if isinstance(error, commands.BadArgument):
        try:
            await ctx.send("❌ Tham số không hợp lệ. Kiểm tra lại mentions/IDs.")
        except Exception:
            pass
        return

    # 5) Các lỗi còn lại: log để dev kiểm tra, nhưng không spam người dùng
    print("Unhandled command error:", error)
    traceback.print_exception(type(error), error, error.__traceback__)
    # Không gửi message cho user -> im lặng
    return

# Slash / app command errors
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """
    Handler cho slash commands.
    - Không thông báo khi lệnh không tồn tại.
    - Có thể thông báo MissingPermissions.
    """
    # Một số lỗi app_commands có cấu trúc khác
    if isinstance(error, app_commands.CommandNotFound):
        # im lặng khi command không biết
        return

    if isinstance(error, app_commands.MissingPermissions):
        try:
            await interaction.response.send_message("❌ Bạn không có quyền thực hiện lệnh này.", ephemeral=True)
        except Exception:
            pass
        return

    # Log những lỗi khác để debug (nhưng không gửi cho user)
    print("Unhandled app command error:", error)
    traceback.print_exception(type(error), error, error.__traceback__)
    # im lặng
    return


# =====================
# HÀM LƯU / TẢI DỮ LIỆU
# =====================
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)  # tạo file rỗng
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(reaction_roles, f, ensure_ascii=False, indent=4)

reaction_roles = load_data()



# =====================
# 1. Slash command: reaction role đơn
# =====================
@bot.tree.command(name="reactionrole", description="Tạo reaction role 1 emoji - 1 role")
@app_commands.describe(channel="Kênh để gửi tin nhắn", emoji="Emoji reaction", role="Role sẽ gán", message="Nội dung hiển thị")
async def reactionrole(interaction: discord.Interaction, channel: discord.TextChannel, emoji: str, role: discord.Role, message: str):
    msg = await channel.send(f"{message}\nReact {emoji} để nhận role {role.mention}")
    await msg.add_reaction(emoji)

    reaction_roles[str(msg.id)] = {emoji: role.id}
    save_data()

    await interaction.response.send_message("✅ Reaction role (1 emoji - 1 role) đã được tạo!", ephemeral=True)


# =====================
# 2. Slash command: reaction role nhiều emoji
# =====================
@bot.tree.command(name="reactionrole_multi", description="Tạo reaction role với nhiều emoji")
@app_commands.describe(channel="Kênh để gửi tin nhắn",
                       pairs="Nhập dạng: emoji1 @role1 , emoji2 @role2 ...",
                       message="Nội dung hiển thị")
async def reactionrole_multi(interaction: discord.Interaction,
                             channel: discord.TextChannel,
                             pairs: str,
                             message: str):
    """
    Ví dụ nhập:
    /reactionrole_multi #roles "😊 @Member , 😎 @VIP , 🎮 @Gamer" "Chọn role của bạn"
    """
    guild = interaction.guild
    mapping = {}

    items = [p.strip() for p in pairs.split(",")]
    lines = []
    for item in items:
        try:
            emoji, role_mention = item.split()
            role_id = int(role_mention.strip("<@&>"))
            role = guild.get_role(role_id)
            if role:
                mapping[emoji] = role.id
                lines.append(f"{emoji} → {role.mention}")
        except Exception:
            return await interaction.response.send_message(f"❌ Sai định dạng: {item}", ephemeral=True)

    content = f"{message}\n\n" + "\n".join(lines)
    msg = await channel.send(content)

    for emoji in mapping.keys():
        try:
            await msg.add_reaction(emoji)
        except:
            return await interaction.response.send_message(f"❌ Không thể add emoji {emoji}", ephemeral=True)

    reaction_roles[str(msg.id)] = mapping
    save_data()

    await interaction.response.send_message("✅ Reaction role (multi) đã được tạo!", ephemeral=True)


# =====================
# Sự kiện: thêm/bỏ reaction
# =====================
@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.message_id) in reaction_roles and not payload.member.bot:
        emoji_roles = reaction_roles[str(payload.message_id)]
        if str(payload.emoji) in emoji_roles:
            guild = bot.get_guild(payload.guild_id)
            role = guild.get_role(emoji_roles[str(payload.emoji)])
            member = guild.get_member(payload.user_id)
            if role and member:
                await member.add_roles(role, reason="Reaction role add")
                print(f"✅ Thêm {role.name} cho {member.display_name}")


@bot.event
async def on_raw_reaction_remove(payload):
    if str(payload.message_id) in reaction_roles:
        emoji_roles = reaction_roles[str(payload.message_id)]
        if str(payload.emoji) in emoji_roles:
            guild = bot.get_guild(payload.guild_id)
            role = guild.get_role(emoji_roles[str(payload.emoji)])
            member = guild.get_member(payload.user_id)
            if role and member:
                await member.remove_roles(role, reason="Reaction role remove")
                print(f"❌ Gỡ {role.name} cho {member.display_name}")

# ---------------log------------------

async def log_action(
    guild: discord.Guild,
    message: str,
    user: discord.Member | discord.User = None,
    color=discord.Color.orange()
):
    ch = discord.utils.get(guild.text_channels, name="mod-log")
    if ch is None:
        try:
            ch = await guild.create_text_channel("mod-log")
        except Exception:
            return

    embed = discord.Embed(
        description=message,
        color=color,
        timestamp=discord.utils.utcnow()
    )

    if user:
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)

    embed.set_footer(text=f"Server: {guild.name}")
    await ch.send(embed=embed)

# Thành viên vào/ra
@bot.event
async def on_member_join(member: discord.Member):
    await log_action(member.guild, f"✅ {member.mention} đã tham gia server.", user=member, color=discord.Color.green())

@bot.event
async def on_member_remove(member: discord.Member):
    await log_action(member.guild, f"👋 {member} đã rời server.", user=member, color=discord.Color.red())

# Update thông tin member
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    changes = []
    if before.nick != after.nick:
        changes.append(f"🔤 Nick đổi: `{before.nick}` → `{after.nick}`")
    if before.roles != after.roles:
        before_roles = {r.id for r in before.roles}
        after_roles = {r.id for r in after.roles}
        added = [r.mention for r in after.roles if r.id not in before_roles]
        removed = [r.name for r in before.roles if r.id not in after_roles]
        if added:
            changes.append(f"➕ Thêm role: {', '.join(added)}")
        if removed:
            changes.append(f"➖ Gỡ role: {', '.join(removed)}")
    if changes:
        await log_action(after.guild, "📝 Update " + " | ".join(changes), user=after, color=discord.Color.blurple())

# Kênh
@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    await log_action(channel.guild, f"📢 Kênh mới tạo: {channel.mention}", color=discord.Color.green())

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    await log_action(channel.guild, f"🗑️ Kênh bị xóa: {channel.name}", color=discord.Color.red())

@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
    if before.name != after.name:
        await log_action(after.guild, f"✏️ Kênh đổi tên: `{before.name}` → `{after.name}`", color=discord.Color.yellow())

# Role
@bot.event
async def on_guild_role_create(role: discord.Role):
    await log_action(role.guild, f"🎭 Role mới tạo: {role.name}", color=discord.Color.green())

@bot.event
async def on_guild_role_delete(role: discord.Role):
    await log_action(role.guild, f"❌ Role bị xóa: {role.name}", color=discord.Color.red())

@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    if before.name != after.name:
        await log_action(after.guild, f"✏️ Role đổi tên: `{before.name}` → `{after.name}`", color=discord.Color.yellow())

# Tin nhắn
@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild and not message.author.bot:
        await log_action(
            message.guild,
            f"🗑️ Tin nhắn bị xóa ở #{message.channel.name}\n**Nội dung:** {message.content}",
            user=message.author,
            color=discord.Color.red()
        )

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.guild and not before.author.bot and before.content != after.content:
        await log_action(
            before.guild,
            f"✏️ Tin nhắn sửa ở #{before.channel.name}\n**Trước:** {before.content}\n**Sau:** {after.content}",
            user=before.author,
            color=discord.Color.yellow()
        )

@bot.command(name="setnick")
@commands.has_permissions(manage_nicknames=True)
async def setnick(ctx, member: discord.Member, *, nickname: str = None):
    """Đổi nickname của 1 thành viên"""
    try:
        old_nick = member.display_name
        await member.edit(nick=nickname)
        if nickname:
            await ctx.send(f"✅ Nickname của {member.mention} đã đổi từ **{old_nick}** thành **{nickname}**")
            await log_action(ctx.guild, f"{ctx.author} đổi nickname {member} từ **{old_nick}** thành **{nickname}**", member)
        else:
            await ctx.send(f"♻️ Nickname của {member.mention} đã được reset về mặc định")
            await log_action(ctx.guild, f"{ctx.author} reset nickname của {member}", member)
    except Exception as e:
        await ctx.send(f"❌ Không thể đổi nickname: {e}")
        

# =====================
# ON READY
# =====================
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Bot đã đăng nhập: {bot.user}")
        print(f"📦 Slash commands đã sync: {len(synced)} lệnh")
    except Exception as e:
        print(f"❌ Lỗi sync slash commands: {e}")    
# =====================
# RUN BOT
# =====================
if __name__ == "__main__":
    bot.run(TOKEN)
