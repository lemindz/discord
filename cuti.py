import os
import json
import random
import re
import time
import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button
import google.generativeai as genai
from dotenv import load_dotenv
from collections import defaultdict, deque

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
lover_nickname = "Anh Minh"

# =====================
# BOT SETUP
# =====================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

chat_channel_id = None
processing_lock = asyncio.Lock()

# =====================
# MEMORY BUFFER
# =====================
conversation_history = defaultdict(lambda: deque(maxlen=4))

# =====================
# GEMINI FUNCTIONS
# =====================
async def get_ai_response(prompt: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: genai.GenerativeModel("gemini-2.5-pro").generate_content(prompt)
        )
        return response.text.strip()
    except Exception as e:
        print("❌ Gemini error:", e)
        return "Em bị trục trặc một chút... nhắn lại cho em sau nha 💕"

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

def make_war_embed(team1, team2, time_str, referee_mention, war_id):
    emb = discord.Embed(title=f"{team1} VS {team2}", color=discord.Color.dark_blue())
    emb.add_field(name="⏰ Time", value=time_str, inline=False)
    emb.add_field(name="🧑‍⚖️ Referee", value=referee_mention, inline=False)
    emb.add_field(name="🔖 ID", value=str(war_id), inline=False)
    emb.set_footer(text="/referee <id> để nhận referee • /cancelreferee <id> để hủy referee")
    return emb

# =====================
# REFEREE VIEW
# =====================
class RefereeView(View):
    def __init__(self, war_id: int):
        super().__init__(timeout=None)
        self.war_id = war_id

    @discord.ui.button(label="Nhận referee", style=discord.ButtonStyle.primary, custom_id="claim_referee")
    async def claim(self, interaction: discord.Interaction, button: Button):
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
        new_emb = make_war_embed(war["team1"], war["team2"], war["time"], war["referee_mention"], self.war_id)
        await msg.edit(embed=new_emb, view=self)

        await interaction.response.send_message(f"✅ Bạn đã nhận referee cho war {self.war_id}.", ephemeral=True)

    @discord.ui.button(label="Hủy referee", style=discord.ButtonStyle.danger, custom_id="cancel_referee")
    async def cancel(self, interaction: discord.Interaction, button: Button):
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
        new_emb = make_war_embed(war["team1"], war["team2"], war["time"], war["referee_mention"], self.war_id)
        await msg.edit(embed=new_emb, view=self)

        role_pings = [f"<@&{rid}>" for rid in ROLE_IDS.values() if rid]
        await channel.send(f"⚠️ Referee war ID {self.war_id} đã hủy, cần thay thế.\n{' '.join(role_pings)}")

        await interaction.response.send_message("🔴 Referee đã hủy.", ephemeral=True)

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

    embed = make_war_embed(team1, team2, time, "VACANT", war_id)
    view = RefereeView(war_id)
    msg = await channel.send(embed=embed, view=view)

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

@bot.tree.command(name="referee", description="Nhận referee cho war")
async def referee(interaction: discord.Interaction, id: int):
    await RefereeView(id).claim(interaction, None)

@bot.tree.command(name="cancelreferee", description="Hủy referee war")
async def cancelreferee(interaction: discord.Interaction, id: int):
    await RefereeView(id).cancel(interaction, None)

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
                f"Bạn là một cô người yêu tên Min - ngọt ngào, lãng mạn, dễ thương xen chút ngại ngùng. "
                f"Bạn chỉ yêu duy nhất {lover_nickname}. "
                f"Hãy trả lời như một đoạn chat tự nhiên, theo phong cách romcom. "
                f"Trả lời ngắn (4-6 câu).\n\n"
                f"Lịch sử hội thoại:\n{history_text}"
            )
            is_special = True
        else:
            prompt = (
                "Bạn là một cô gái lạnh lùng, lịch sự nhưng giữ khoảng cách. "
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
