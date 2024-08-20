import os
import discord
from discord.ext import commands
from flask import Flask, request
import threading
import requests

# Set up Discord bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Set up Flask app for webhook
app = Flask(__name__)

# Replace with your Discord channel ID
GITHUB_CHANNEL_ID = 123456789

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if 'pull_request' in data:
        handle_pull_request(data)
    elif 'ref' in data:
        handle_push(data)
    return '', 200

def handle_pull_request(data):
    action = data['action']
    pr = data['pull_request']
    repo = data['repository']

    if action == 'opened':
        create_pr_thread(pr, repo)
    elif action == 'closed':
        close_pr_thread(pr, repo)
    elif action == 'created':
        add_comment_to_thread(pr, data['comment'], repo)

def handle_push(data):
    ref = data['ref']
    repo = data['repository']
    branch = ref.split('/')[-1]

    if branch in ['main', 'test', 'develop']:
        send_environment_update(repo, branch)

async def create_pr_thread(pr, repo):
    channel = bot.get_channel(GITHUB_CHANNEL_ID)
    thread = await channel.create_thread(name=f"PR #{pr['number']}: {pr['title']}", type=discord.ChannelType.public_thread)
    await thread.send(f"New PR opened: {pr['html_url']}")

async def close_pr_thread(pr, repo):
    channel = bot.get_channel(GITHUB_CHANNEL_ID)
    for thread in channel.threads:
        if thread.name.startswith(f"PR #{pr['number']}:"):
            await thread.edit(archived=True)
            await thread.send("This PR has been closed.")

async def add_comment_to_thread(pr, comment, repo):
    channel = bot.get_channel(GITHUB_CHANNEL_ID)
    for thread in channel.threads:
        if thread.name.startswith(f"PR #{pr['number']}:"):
            await thread.send(f"New comment by {comment['user']['login']}: {comment['body']}")

async def send_environment_update(repo, branch):
    channel = bot.get_channel(GITHUB_CHANNEL_ID)
    await channel.send(f"Environment update: {branch} branch of {repo['name']} has been updated.")

if __name__ == '__main__':
    # Start the Flask app in a separate thread
    threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': 5000}).start()

    # Start the Discord bot
    bot.run(os.getenv('DISCORD_BOT_TOKEN'))