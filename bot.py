import os
import json
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

# Load repository to channel mapping from environment variable
REPO_CHANNEL_MAPPING = json.loads(os.getenv('REPO_CHANNEL_MAPPING', '{}'))

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    repo_name = data['repository']['full_name']
    
    if repo_name not in REPO_CHANNEL_MAPPING:
        print(f"Received webhook for unmapped repository: {repo_name}")
        return '', 200

    if 'pull_request' in data:
        handle_pull_request(data, repo_name)
    elif 'ref' in data:
        handle_push(data, repo_name)
    return '', 200

def handle_pull_request(data, repo_name):
    action = data['action']
    pr = data['pull_request']

    if action == 'opened':
        create_pr_thread(pr, repo_name)
    elif action == 'closed':
        close_pr_thread(pr, repo_name)
    elif action == 'created':
        add_comment_to_thread(pr, data['comment'], repo_name)

def handle_push(data, repo_name):
    ref = data['ref']
    branch = ref.split('/')[-1]

    if branch in ['main', 'test', 'develop']:
        send_environment_update(repo_name, branch)

async def create_pr_thread(pr, repo_name):
    channel_id = REPO_CHANNEL_MAPPING[repo_name]
    channel = bot.get_channel(int(channel_id))
    thread = await channel.create_thread(name=f"PR #{pr['number']}: {pr['title']}", type=discord.ChannelType.public_thread)
    await thread.send(f"New PR opened in {repo_name}: {pr['html_url']}")

async def close_pr_thread(pr, repo_name):
    channel_id = REPO_CHANNEL_MAPPING[repo_name]
    channel = bot.get_channel(int(channel_id))
    for thread in channel.threads:
        if thread.name.startswith(f"PR #{pr['number']}:"):
            await thread.edit(archived=True)
            await thread.send(f"This PR in {repo_name} has been closed.")

async def add_comment_to_thread(pr, comment, repo_name):
    channel_id = REPO_CHANNEL_MAPPING[repo_name]
    channel = bot.get_channel(int(channel_id))
    for thread in channel.threads:
        if thread.name.startswith(f"PR #{pr['number']}:"):
            await thread.send(f"New comment in {repo_name} by {comment['user']['login']}: {comment['body']}")

async def send_environment_update(repo_name, branch):
    channel_id = REPO_CHANNEL_MAPPING[repo_name]
    channel = bot.get_channel(int(channel_id))
    await channel.send(f"Environment update: {branch} branch of {repo_name} has been updated.")

@bot.command(name='link')
@commands.has_permissions(administrator=True)
async def link_repo(ctx, repo_name: str):
    """Link a GitHub repository to this channel."""
    global REPO_CHANNEL_MAPPING
    REPO_CHANNEL_MAPPING[repo_name] = str(ctx.channel.id)
    await ctx.send(f"Linked {repo_name} to this channel.")
    # Here you might want to update the environment variable or a database
    # This example just updates the in-memory dictionary
    print(f"Updated REPO_CHANNEL_MAPPING: {REPO_CHANNEL_MAPPING}")

if __name__ == '__main__':
    # Start the Flask app in a separate thread
    port = int(os.environ.get('PORT', 5000))
    threading.Thread(target=app.run, kwargs={'host': '0.0.0.0', 'port': port}).start()

    # Start the Discord bot
    bot.run(os.getenv('DISCORD_BOT_TOKEN'))