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

# Hàm gọi API Gemini
def get_ai_response(prompt):
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt
    )
    return response.text.strip()

# Sự kiện khi bot đã sẵn sàng
@bot.event
async def on_ready():
    print(f"Bot đã sẵn sàng với tên: {bot.user}")

# Sự kiện khi nhận tin nhắn
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user in message.mentions:
        user_message = message.content.replace(f"<@{bot.user.id}>", "").strip()
        prompt = f"Bạn là một cô người yêu ngọt ngào và lãng mạn, xen chút ngại ngùng và lúng túng khi được bày tỏ tình cảm
        trả lời ngắn gọn trong 2-3 câu. Trả lời người yêu của bạn: {user_message}"
        ai_reply = get_ai_response(prompt)
        await message.channel.send(ai_reply)

    await bot.process_commands(message)

bot.run(os.getenv("DISCORD_TOKEN"))
