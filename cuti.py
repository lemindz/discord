import discord
from discord.ext import commands
import os
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

# Hàm gọi API Gemini
def get_ai_response(prompt):
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt
    )
    return response.text.strip()

# Giới hạn số câu trả lời
def limit_sentences(text, max_sentences=3):
    sentences = text.replace("!", ".").replace("?", ".").split(".")
    limited = ".".join([s.strip() for s in sentences if s.strip()][:max_sentences])
    return limited.strip() + ("." if not limited.strip().endswith(".") else "")

# Sự kiện khi bot sẵn sàng
@bot.event
async def on_ready():
    await bot.tree.sync()  # Đồng bộ slash commands
    print(f"Bot đã sẵn sàng với tên: {bot.user}")

# Slash command để set kênh chat (chỉ admin)
@bot.tree.command(name="setchannel", description="Chọn kênh để bot chat khi được tag")
async def setchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    global chat_channel_id

    # Kiểm tra quyền admin
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message("❌ Bạn không có quyền dùng lệnh này.", ephemeral=True)
        return

    chat_channel_id = channel.id
    await interaction.response.send_message(f"✅ Bot sẽ chỉ chat trong kênh: {channel.mention}")

# Slash command để reset kênh chat (chỉ admin)
@bot.tree.command(name="clearchannel", description="Reset để bot chat ở tất cả kênh")
async def clearchannel(interaction: discord.Interaction):
    global chat_channel_id

    # Kiểm tra quyền admin
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
        prompt = f"Bạn là một cô người yêu tsundere ngọt ngào, lãng mạn, xen chút lúng túng, ngại ngùng. \hãy trả lời người yêu của bạn trong 2-3 câu ngắn gọn: {user_message}"
        ai_reply = get_ai_response(prompt)
        ai_reply = limit_sentences(ai_reply, 3)
        await message.channel.send(ai_reply)

    await bot.process_commands(message)

bot.run(os.getenv("DISCORD_TOKEN"))
