from tgkit import File, Sticker, Userbot, f

bot = Userbot("config.json")

# Send: one function, the content decides what is sent
# bot.send("@lain", "hello")
# bot.send("@lain", File("photo.jpg", caption="a photo"))
# bot.send("@lain", File("song.mp3"), at="2026-11-06 09:00")   # scheduled

# Reply to a message you have (from read or from a hook)
# last = bot.messages("@lain", limit=1)[0]
# last.reply("got it")
# last.reply(Sticker("me", 742))

# Read, search, download
# for m in bot.messages("@lain", limit=20, types=["photo"]):
#     print(m.id, m.date, m.text)
# bot.download_all("@lain", types=["video", "file"], limit=100)

# Hooks: a condition built from filters, and a plain function
@bot.on(f.private & f.from_user("r4x7a") & f.text)
def greet(msg):
    msg.reply("Hello from tgkit")


if __name__ == "__main__":
    bot.run()
