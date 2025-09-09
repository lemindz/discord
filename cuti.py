import discord
from discord.ext import commands
import os
import random
import time
import asyncio
from google import genai
from dotenv import load_dotenv

load_dotenv()

# Khởi tạo client Gemini
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Khởi tạo bot Discord
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Biến lưu kênh chat (None = mọi kênh)
chat_channel_id = None

# Cooldown + lock
last_reply_time = 0
cooldown_seconds = 5
processing_lock = asyncio.Lock()

# Hàm gọi API Gemini
def get_ai_response(prompt):
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt
    )
    return response.text.strip()

# Giới hạn chính xác 2 hoặc 3 câu (random)
def limit_exact_sentences(text):
    target_sentences = random.choice([4, 6])
    sentences = text.replace("!", ".").replace("?", ".").split(".")
    sentences = [s.strip() for s in sentences if s.strip()]
    limited = ".".join(sentences[:target_sentences])
    return limited.strip() + ("." if not limited.strip().endswith(".") else "")

# Safe reply (có cooldown)
async def safe_reply(message, ai_reply):
    global last_reply_time
    now = time.time()
    if now - last_reply_time < cooldown_seconds:
        return  # bỏ qua nếu chưa hết cooldown
    last_reply_time = now
    await message.channel.send(ai_reply)

# Sự kiện khi bot sẵn sàng
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot đã sẵn sàng với tên: {bot.user}")

# Slash command để set kênh chat (chỉ admin)
@bot.tree.command(name="setchannel", description="Chọn kênh để bot chat khi được tag")
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    global chat_channel_id

    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return

    chat_channel_id = channel.id
    await interaction.response.send_message(f"✅ Bot sẽ chỉ chat trong kênh: {channel.mention}")

# Slash command để reset kênh chat (chỉ admin)
@bot.tree.command(name="clearchannel", description="Reset để bot chat ở tất cả kênh")
async def clearchannel(interaction: discord.Interaction):
    global chat_channel_id

    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return

    chat_channel_id = None
    await interaction.response.send_message("♻️ Bot đã được reset, giờ sẽ chat ở **tất cả các kênh** khi được tag.")

# Sự kiện nhận tin nhắn
@bot.event
async def on_message(message):
    global chat_channel_id
    if message.author == bot.user:
        return

    # Nếu đã set channel → chỉ trả lời ở channel đó
    if chat_channel_id and message.channel.id != chat_channel_id:
        return

    if bot.user in message.mentions:
        user_message = message.content.replace(f"<@{bot.user.id}>", "").strip()
        user_message = user_message[:300]  # giới hạn 300 ký tự

        async with processing_lock:  # chỉ xử lý 1 request 1 lúc
            prompt = f"Bạn là một cô người yêu ngọt ngào, lãng mạn, xen chút ngại ngùng. \
            Hãy trả lời người yêu của bạn bằng đúng 4 hoặc 6 câu ngắn gọn, tình cảm và dễ thương: {user_message}"

            ai_reply = get_ai_response(prompt)
            ai_reply = limit_exact_sentences(ai_reply)
            await safe_reply(message, ai_reply)

    await bot.process_commands(message)

bot.run(os.getenv("DISCORD_TOKEN"))
