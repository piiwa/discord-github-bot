import os
import json
import discord
from discord.ext import commands
from flask import Flask, request
import threading
import aiohttp
import asyncio
import logging
from logging.handlers import RotatingFileHandler

# Set up logging
logger = logging.getLogger('discord_github_bot')
logger.setLevel(logging.DEBUG)
handler = RotatingFileHandler('discord_github_bot.log', maxBytes=10000000, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Also log to console
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

class GitHubBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.github_channel_id = int(os.getenv('GITHUB_CHANNEL_ID'))
        self.github_api_base = "https://api.github.com"
        self.github_token = os.getenv('GITHUB_TOKEN')

    async def setup_hook(self):
        logger.info("Bot is setting up...")
        await self.sync_repo()

    async def sync_repo(self):
        logger.info("Starting repository sync")
        headers = {"Authorization": f"token {self.github_token}"} if self.github_token else {}
        async with aiohttp.ClientSession(headers=headers) as session:
            url = f"{self.github_api_base}/repos/{self.github_repo}/pulls?state=open"
            logger.info(f"Fetching open PRs from: {url}")
            async with session.get(url) as response:
                logger.info(f"API response status: {response.status}")
                if response.status == 200:
                    prs = await response.json()
                    logger.info(f"Found {len(prs)} open PRs")
                    for pr in prs:
                        logger.info(f"Processing PR #{pr['number']}: {pr['title']}")
                        await self.create_pr_thread(pr)
                else:
                    logger.error(f"Failed to fetch PRs. Status: {response.status}, Response: {await response.text()}")

    async def handle_github_event(self, data):
        logger.info(f"Handling GitHub event: {json.dumps(data)[:500]}...")
        try:
            repo_name = data['repository']['full_name'] if 'repository' in data else 'Unknown repository'
            logger.info(f"Event from repository: {repo_name}")

            if 'pull_request' in data and 'action' in data:
                if data['action'] == 'opened':
                    await self.handle_pull_request(data)
                elif data['action'] in ['closed', 'merged']:
                    await self.handle_pr_closure(data['pull_request'])
            elif 'review' in data:
                await self.handle_pr_review(data)
            elif 'comment' in data:
                await self.handle_pr_comment(data)
            elif 'ref' in data:
                await self.handle_push(data)
            else:
                logger.warning(f"Received unknown event type from {repo_name}: {json.dumps(data)[:500]}...")
        except Exception as e:
            logger.error(f"Error handling GitHub event: {str(e)}", exc_info=True)

    async def handle_pull_request(self, data):
        action = data['action']
        pr = data['pull_request']
        logger.info(f"Handling PR {pr['number']} - Action: {action}")

        try:
            if action == 'opened':
                await self.create_pr_thread(pr)
            elif action == 'closed':
                await self.close_pr_thread(pr)
            elif action == 'created':
                await self.add_comment_to_thread(pr, data['comment'])
            else:
                logger.info(f"Unhandled PR action: {action}")
        except Exception as e:
            logger.error(f"Error handling PR {pr['number']}: {str(e)}", exc_info=True)

    async def handle_push(self, data):
        ref = data['ref']
        branch = ref.split('/')[-1]
        logger.info(f"Handling push to branch: {branch}")

        try:
            if branch in ['main', 'test', 'develop']:
                await self.send_environment_update(branch)
            else:
                logger.info(f"Push to non-environment branch: {branch}")
        except Exception as e:
            logger.error(f"Error handling push to {branch}: {str(e)}", exc_info=True)

    async def handle_pr_closure(self, pr):
        logger.info(f"Handling closure of PR #{pr['number']}")
        try:
            channel = self.get_channel(self.github_channel_id)
            thread = await self.get_thread(channel, pr)
            if thread:
                await self.close_pr_thread(pr, thread)
            else:
                logger.warning(f"No thread found for closed PR #{pr['number']}")
        except Exception as e:
            logger.error(f"Error handling closure of PR {pr['number']}: {str(e)}", exc_info=True)

    async def close_pr_thread(self, pr, thread):
        logger.info(f"Closing thread for PR #{pr['number']}")
        try:
            closure_message = f"PR #{pr['number']} has been {'merged' if pr['merged'] else 'closed'}."
            await thread.send(closure_message)
            await thread.edit(archived=True, locked=True, name=f"[CLOSED] {thread.name}")
            logger.info(f"Thread closed for PR #{pr['number']}")
        except discord.errors.Forbidden:
            logger.error(f"Bot doesn't have permission to close thread for PR #{pr['number']}")
        except discord.errors.HTTPException as e:
            logger.error(f"HTTP exception when closing thread for PR #{pr['number']}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error when closing thread for PR #{pr['number']}: {str(e)}", exc_info=True)

    async def handle_pr_review(self, data):
        pr = data['pull_request']
        review = data['review']
        repo_name = data['repository']['full_name']
        logger.info(f"Handling review on PR #{pr['number']} in {repo_name}")

        try:
            channel = self.get_channel(self.github_channel_id)
            thread = await self.get_thread(channel, pr, repo_name)
            if thread:
                await self.add_review_to_thread(pr, review, thread, repo_name)
            else:
                logger.warning(f"No thread found for review on PR #{pr['number']} in {repo_name}")
        except Exception as e:
            logger.error(f"Error handling review on PR {pr['number']} in {repo_name}: {str(e)}", exc_info=True)

    async def handle_pr_comment(self, data):
        repo_name = data['repository']['full_name']
        if 'issue' in data:
            pr_number = data['issue']['number']
            comment = data['comment']
        elif 'pull_request' in data:
            pr_number = data['pull_request']['number']
            comment = data['comment']
        else:
            logger.warning(f"Received comment event from {repo_name}, but couldn't determine PR number")
            return

        logger.info(f"Handling comment on PR #{pr_number} in {repo_name}")

        try:
            channel = self.get_channel(self.github_channel_id)
            thread = await self.get_thread(channel, {'number': pr_number}, repo_name)
            if thread:
                await self.add_comment_to_thread({'number': pr_number}, comment, thread, repo_name)
            else:
                logger.warning(f"No thread found for comment on PR #{pr_number} in {repo_name}")
        except Exception as e:
            logger.error(f"Error handling comment on PR {pr_number} in {repo_name}: {str(e)}", exc_info=True)

    async def get_thread(self, channel, pr, repo_name):
        logger.info(f"Searching for thread for PR #{pr['number']} in {repo_name}")
        thread_name = f"[{repo_name}] PR #{pr['number']}:"
        for thread in channel.threads:
            if thread.name.startswith(thread_name):
                logger.info(f"Found thread for PR #{pr['number']} in {repo_name}: {thread.name}")
                return thread
        logger.warning(f"No thread found for PR #{pr['number']} in {repo_name}")
        return None

    async def add_review_to_thread(self, pr, review, thread, repo_name):
        logger.info(f"Adding review to thread for PR #{pr['number']} in {repo_name}")
        review_state = review['state'].capitalize()
        review_body = review['body'] if review['body'] else "No comment provided."
        message = f"New review by {review['user']['login']} - {review_state}:\n{review_body}"
        await thread.send(message)
        logger.info(f"Review added to thread for PR #{pr['number']} in {repo_name}")

    async def add_comment_to_thread(self, pr, comment, thread, repo_name):
        logger.info(f"Adding comment to thread for PR #{pr['number']} in {repo_name}")
        message = f"New comment by {comment['user']['login']}:\n{comment['body']}"
        await thread.send(message)
        logger.info(f"Comment added to thread for PR #{pr['number']} in {repo_name}")

    async def create_pr_thread(self, pr, repo_name):
        logger.info(f"Attempting to create thread for PR #{pr['number']} in {repo_name}")
        channel = self.get_channel(self.github_channel_id)
        if not channel:
            logger.error(f"Unable to find channel with ID {self.github_channel_id}")
            return

        logger.info(f"Found channel: {channel.name} (ID: {channel.id})")
        
        thread_name = f"[{repo_name}] PR #{pr['number']}: {pr['title']}"
        existing_thread = discord.utils.get(channel.threads, name=thread_name)
        if existing_thread:
            logger.info(f"Thread for PR #{pr['number']} in {repo_name} already exists")
            return existing_thread

        try:
            thread = await channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.public_thread
            )
            logger.info(f"Successfully created thread for PR #{pr['number']} in {repo_name}")
            await thread.send(f"A new Pull Request is live here: {pr['html_url']} and created by {pr['user']['login']}.")
            logger.info(f"Sent initial message in thread for PR #{pr['number']} in {repo_name}")
            return thread
        except Exception as e:
            logger.error(f"Error creating thread for PR #{pr['number']} in {repo_name}: {str(e)}", exc_info=True)
            return None
  
    async def get_or_create_thread(self, channel, pr):
        thread = await self.get_thread(channel, pr)
        if thread:
            return thread
        
        # If thread doesn't exist, create a new one
        return await self.create_pr_thread(pr)

    async def send_environment_update(self, branch):
        logger.info(f"Sending environment update for branch: {branch}")
        channel = self.get_channel(self.github_channel_id)
        await channel.send(f"Environment update: {branch} branch has been updated.")
        logger.info(f"Environment update sent for branch: {branch}")

intents = discord.Intents.default()
intents.message_content = True
bot = GitHubBot(command_prefix='!', intents=intents)

app = Flask(__name__)

@bot.event
async def on_ready():
    logger.info(f'Bot {bot.user} has connected to Discord!')

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    logger.info(f"Received webhook: {json.dumps(data)[:500]}...")  # Log more of the webhook data
    
    # Use run_coroutine_threadsafe to run the coroutine in the bot's event loop
    future = asyncio.run_coroutine_threadsafe(bot.handle_github_event(data), bot.loop)
    try:
        future.result(timeout=60)  # Wait for at most 60 seconds
    except asyncio.TimeoutError:
        logger.error("Webhook handling timed out")
    except Exception as e:
        logger.error(f"Error in webhook handling: {str(e)}", exc_info=True)
    
    return '', 200

@bot.command(name='status')
async def status(ctx):
    """Check the status of the bot and its connections."""
    logger.info("Status command invoked")
    try:
        channel = bot.get_channel(bot.github_channel_id)
        if channel:
            await ctx.send(f"Bot is running. Connected to GitHub channel: {channel.name}")
        else:
            await ctx.send("Bot is running, but GitHub channel not found. Check GITHUB_CHANNEL_ID.")
        logger.info("Status command completed successfully")
    except Exception as e:
        logger.error(f"Error in status command: {str(e)}", exc_info=True)
        await ctx.send("An error occurred while checking status. Please check the logs.")

@bot.command(name='sync')
@commands.has_permissions(administrator=True)
async def sync(ctx):
    """Manually trigger a sync of open PRs."""
    logger.info("Sync command invoked")
    await ctx.send("Syncing open PRs...")
    await bot.sync_repo()
    await ctx.send("Sync completed.")

@bot.command(name='list_prs')
async def list_prs(ctx):
    """List all open PRs."""
    logger.info("List PRs command invoked")
    channel = bot.get_channel(bot.github_channel_id)
    open_prs = [thread for thread in channel.threads if thread.name.startswith("PR #")]
    if open_prs:
        pr_list = "\n".join([thread.name for thread in open_prs])
        await ctx.send(f"Open PRs:\n{pr_list}")
    else:
        await ctx.send("No open PRs found.")

@bot.command(name='commands')
async def custom_help(ctx):
    """Display custom help message with available commands."""
    help_text = """
    Available commands:
    - !status: Check the status of the bot and its connections.
    - !sync: Manually trigger a sync of open PRs (Admin only).
    - !list_prs: List all open PRs.
    - !commands: Display this help message.
    """
    await ctx.send(help_text)

if __name__ == '__main__':
    logger.info("Starting bot")
    
    # Start the Discord bot in a separate thread
    bot_thread = threading.Thread(target=bot.run, args=(os.getenv('DISCORD_BOT_TOKEN'),))
    bot_thread.start()
    
    # Start the Flask app in the main thread
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)