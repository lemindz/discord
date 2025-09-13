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
last_reply_time = 0
cooldown_seconds = 5
processing_lock = asyncio.Lock()

# =====================
# GEMINI FUNCTIONS
# =====================
async def get_ai_response(prompt: str) -> str:
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: genai.GenerativeModel("gemini-2.5-flash").generate_content(prompt)
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
# TICKET SYSTEM
# =====================
class TicketPanelView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="challenge/spar", emoji="📩", style=discord.ButtonStyle.blurple, custom_id="ticket_challenge")
    async def challenge_btn(self, interaction: discord.Interaction, button: Button):
        await self.create_ticket(interaction, "challenge-spar")

    @discord.ui.button(label="hỗ trợ", emoji="📩", style=discord.ButtonStyle.green, custom_id="ticket_support")
    async def support_btn(self, interaction: discord.Interaction, button: Button):
        await self.create_ticket(interaction, "support")

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str):
        guild = interaction.guild
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if not category:
            return await interaction.response.send_message("❌ Category ticket không tồn tại.", ephemeral=True)

        existing = discord.utils.get(guild.text_channels, name=f"{ticket_type}-{interaction.user.id}")
        if existing:
            return await interaction.response.send_message(f"Bạn đã có ticket: {existing.mention}", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        support_role = guild.get_role(SUPPORT_ROLE_ID)
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        ticket_channel = await guild.create_text_channel(
            name=f"{ticket_type}-{interaction.user.id}",
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title=f"🎫 Ticket {ticket_type}",
            description=f"Xin chào {interaction.user.mention}, staff sẽ hỗ trợ bạn sớm.\nNhấn nút để đóng ticket.",
            color=discord.Color.green()
        )
        view = CloseTicketView(ticket_channel.id)
        await ticket_channel.send(embed=embed, view=view)

        await interaction.response.send_message(f"✅ Ticket tạo: {ticket_channel.mention}", ephemeral=True)

class CloseTicketView(View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="Đóng ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_btn(self, interaction: discord.Interaction, button: Button):
        channel = interaction.guild.get_channel(self.channel_id)
        if not channel:
            return await interaction.response.send_message("❌ Ticket không tồn tại.", ephemeral=True)
        await interaction.response.send_message("🔒 Ticket sẽ đóng sau 5s...", ephemeral=True)
        await asyncio.sleep(5)
        await channel.delete()

@bot.tree.command(name="ticketpanel", description="Gửi panel mở ticket")
async def ticketpanel(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Vui Lòng Tạo Đúng Ticket",
        description="⚡ Tạo ticket nếu bạn muốn **challenge/spar** hoặc **hỗ trợ**\n🕒 Support 24/7 (maybe)\n✅ Rep dưới 5 phút (maybe not 😉)",
        color=discord.Color.blue()
    )
    view = TicketPanelView()
    await interaction.response.send_message(embed=embed, view=view)
# =====================
# Bộ nhớ hội thoại
# =====================
chat_history = {}  # Lưu hội thoại theo user_id

def add_to_history(user_id: int, role: str, content: str, max_messages=4):
    """Thêm tin nhắn vào lịch sử hội thoại"""
    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append({"role": role, "content": content})
    # Chỉ giữ lại 4 tin nhắn gần nhất
    if len(chat_history[user_id]) > max_messages:
        chat_history[user_id] = chat_history[user_id][-max_messages:]

def build_prompt(user_id: int, user_message: str, is_special: bool) -> str:
    """Ghép prompt từ lịch sử + câu nói mới nhất"""
    history = chat_history.get(user_id, [])
    convo = "\n".join([f"{h['role']}: {h['content']}" for h in history])
    
    if is_special:
        system_prompt = (
            f"Bạn là một cô người yêu tên Min - ngọt ngào, lãng mạn, dễ thương xen chút ngại ngùng. "
            f"Bạn chỉ yêu duy nhất {lover_nickname}, và luôn xưng hô với {lover_nickname}. "
            "Hãy trả lời giống truyện romcom, giữ câu trả lời tự nhiên, tình cảm (4-6 câu)."
        )
    else:
        system_prompt = (
            "Bạn là một cô gái dễ thương, lịch sự nhưng giữ khoảng cách. "
            "Hãy trả lời ngắn gọn (2-3 câu), lịch sự, không quá tình cảm."
        )

    return f"{system_prompt}\n\nCuộc hội thoại gần đây:\n{convo}\n\nUser: \"{user_message}\"\nBạn:"

# =====================
# Xử lý mention
# =====================
@bot.event
async def on_message(message: discord.Message):
    global lover_nickname
    if message.author.bot:
        return

    if bot.user in message.mentions:
        user_message = message.content.replace(f"<@{bot.user.id}>", "").strip()[:300]

        if message.author.id == SPECIAL_USER_ID:
            is_special = True
        else:
            is_special = False

        # Thêm tin nhắn user vào lịch sử
        add_to_history(message.author.id, "User", user_message)

        # Xây prompt từ lịch sử
        prompt = build_prompt(message.author.id, user_message, is_special)

        ai_reply = await get_ai_response(prompt)
        ai_reply = limit_exact_sentences(ai_reply, is_special)

        # Thêm câu trả lời của bot vào lịch sử
        add_to_history(message.author.id, "Bot", ai_reply)

        await message.channel.send(ai_reply)

    await bot.process_commands(message)

# =====================
# CHANNEL CONTROL
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
    await bot.tree.sync()
    print(f"✅ Bot đã đăng nhập thành công: {bot.user}")

# =====================
# RUN BOT
# =====================
if __name__ == "__main__":
    bot.run(TOKEN)
                  
