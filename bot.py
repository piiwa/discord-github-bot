import os
import json
import hmac
import hashlib
import discord
from discord.ext import commands
from flask import Flask, request, abort
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
        self.github_webhook_secret = os.getenv('GITHUB_WEBHOOK_SECRET')
        self.session = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        logger.info("Bot is setting up...")
        try:
            await self.sync_repos()
        except Exception as e:
            logger.error(f"Error during setup: {str(e)}", exc_info=True)

    async def close(self):
        await super().close()
        if self.session:
            await self.session.close()

    async def sync_repos(self):
        logger.info("Starting repository sync")
        # This method can be expanded later to sync multiple repositories if needed
        logger.info("Repository sync completed")

    async def handle_github_event(self, data):
        logger.info(f"Handling GitHub event: {json.dumps(data)[:500]}...")
        try:
            repo_name = data['repository']['full_name'] if 'repository' in data else 'Unknown repository'
            logger.info(f"Event from repository: {repo_name}")

            if 'pull_request' in data and 'action' in data:
                if data['action'] == 'opened':
                    await self.handle_pull_request(data, repo_name)
                elif data['action'] in ['closed', 'merged']:
                    await self.handle_pr_closure(data['pull_request'], repo_name)
            elif 'review' in data:
                await self.handle_pr_review(data, repo_name)
            elif 'comment' in data:
                if 'pull_request' in data or ('issue' in data and 'pull_request' in data['issue']):
                    await self.handle_pr_comment(data, repo_name)
            elif 'ref' in data:
                await self.handle_push(data, repo_name)
            else:
                logger.warning(f"Received unknown event type from {repo_name}: {json.dumps(data)[:500]}...")
        except Exception as e:
            logger.error(f"Error handling GitHub event: {str(e)}", exc_info=True)

    async def handle_pull_request(self, data, repo_name):
        action = data['action']
        pr = data['pull_request']
        logger.info(f"Handling PR {pr['number']} in {repo_name} - Action: {action}")

        try:
            if action == 'opened':
                await self.create_pr_thread(pr, repo_name)
            elif action == 'closed':
                await self.close_pr_thread(pr, repo_name)
            else:
                logger.info(f"Unhandled PR action: {action}")
        except Exception as e:
            logger.error(f"Error handling PR {pr['number']} in {repo_name}: {str(e)}", exc_info=True)

    async def handle_pr_review(self, data, repo_name):
        logger.info(f"Handling PR review in {repo_name}")
        try:
            pr = data['pull_request']
            review = data['review']
            action = data['action']
            
            channel = self.get_channel(self.github_channel_id)
            thread = await self.get_or_create_thread(channel, pr, repo_name)
            if thread:
                if action == 'submitted':
                    await self.add_review_to_thread(pr, review, thread, repo_name)
                elif action == 'edited':
                    await self.edit_review_in_thread(pr, review, thread, repo_name)
                elif action == 'dismissed':
                    await self.dismiss_review_in_thread(pr, review, thread, repo_name)
            else:
                logger.warning(f"No thread found for review on PR #{pr['number']} in {repo_name}")
        except Exception as e:
            logger.error(f"Error handling review in {repo_name}: {str(e)}", exc_info=True)

    async def handle_pr_comment(self, data, repo_name):
        logger.info(f"Handling PR comment in {repo_name}")
        try:
            if 'issue' in data:
                pr_number = data['issue']['number']
                pr = await self.get_pr_info(repo_name, pr_number)
            else:
                pr = data['pull_request']
            comment = data['comment']
            action = data['action']

            channel = self.get_channel(self.github_channel_id)
            thread = await self.get_or_create_thread(channel, pr, repo_name)
            if thread:
                if action == 'created':
                    await self.add_comment_to_thread(pr, comment, thread, repo_name)
                elif action == 'edited':
                    await self.edit_comment_in_thread(pr, comment, thread, repo_name)
                elif action == 'deleted':
                    await self.delete_comment_in_thread(pr, comment, thread, repo_name)
            else:
                logger.warning(f"No thread found for comment on PR #{pr['number']} in {repo_name}")
        except Exception as e:
            logger.error(f"Error handling comment in {repo_name}: {str(e)}", exc_info=True)

    async def handle_push(self, data, repo_name):
        ref = data['ref']
        branch = ref.split('/')[-1]
        logger.info(f"Handling push to branch: {branch} in {repo_name}")

        try:
            if branch in ['main', 'test', 'develop']:
                await self.send_environment_update(branch, repo_name)
            else:
                logger.info(f"Push to non-environment branch: {branch} in {repo_name}")
        except Exception as e:
            logger.error(f"Error handling push to {branch} in {repo_name}: {str(e)}", exc_info=True)

    async def get_or_create_thread(self, channel, pr, repo_name):
        thread_name = f"[{repo_name}] PR #{pr['number']}: {pr['title'][:50]}"
        thread = discord.utils.get(channel.threads, name=thread_name)
        if not thread:
            try:
                thread = await channel.create_thread(name=thread_name, type=discord.ChannelType.public_thread)
                await thread.send(f"New PR opened: {pr['html_url']}")
            except discord.HTTPException as e:
                logger.error(f"Failed to create thread for PR #{pr['number']} in {repo_name}: {str(e)}")
                return None
        return thread

    async def create_pr_thread(self, pr, repo_name):
        logger.info(f"Creating thread for PR #{pr['number']} in {repo_name}")
        channel = self.get_channel(self.github_channel_id)
        thread = await self.get_or_create_thread(channel, pr, repo_name)
        if thread:
            await thread.send(f"PR #{pr['number']} opened by {pr['user']['login']}\nTitle: {pr['title']}\nDescription: {pr['body'][:1000]}...")
        else:
            logger.error(f"Failed to create thread for PR #{pr['number']} in {repo_name}")

    async def close_pr_thread(self, pr, repo_name):
        logger.info(f"Closing thread for PR #{pr['number']} in {repo_name}")
        channel = self.get_channel(self.github_channel_id)
        thread = await self.get_or_create_thread(channel, pr, repo_name)
        if thread:
            await thread.send(f"PR #{pr['number']} has been {'merged' if pr['merged'] else 'closed'}.")
            await thread.edit(archived=True, locked=True, name=f"[CLOSED] {thread.name}")
        else:
            logger.error(f"Failed to close thread for PR #{pr['number']} in {repo_name}")

    async def add_review_to_thread(self, pr, review, thread, repo_name):
        logger.info(f"Adding review to thread for PR #{pr['number']} in {repo_name}")
        review_state = review['state'].capitalize()
        review_body = review['body'] if review['body'] else "No comment provided."
        message = f"New review by {review['user']['login']} - {review_state}:\n{review_body}"
        await thread.send(message)

    async def edit_review_in_thread(self, pr, review, thread, repo_name):
        logger.info(f"Editing review in thread for PR #{pr['number']} in {repo_name}")
        message = f"Review by {review['user']['login']} edited:\n{review['body']}"
        await thread.send(message)

    async def dismiss_review_in_thread(self, pr, review, thread, repo_name):
        logger.info(f"Dismissing review in thread for PR #{pr['number']} in {repo_name}")
        message = f"Review by {review['user']['login']} dismissed."
        await thread.send(message)

    async def add_comment_to_thread(self, pr, comment, thread, repo_name):
        logger.info(f"Adding comment to thread for PR #{pr['number']} in {repo_name}")
        message = f"New comment by {comment['user']['login']}:\n{comment['body']}"
        await thread.send(message)

    async def edit_comment_in_thread(self, pr, comment, thread, repo_name):
        logger.info(f"Editing comment in thread for PR #{pr['number']} in {repo_name}")
        message = f"Comment by {comment['user']['login']} edited:\n{comment['body']}"
        await thread.send(message)

    async def delete_comment_in_thread(self, pr, comment, thread, repo_name):
        logger.info(f"Deleting comment in thread for PR #{pr['number']} in {repo_name}")
        message = f"Comment by {comment['user']['login']} was deleted."
        await thread.send(message)

    async def send_environment_update(self, branch, repo_name):
        logger.info(f"Sending environment update for branch: {branch} in {repo_name}")
        channel = self.get_channel(self.github_channel_id)
        await channel.send(f"Environment update: {branch} branch has been updated in {repo_name}.")

    async def get_pr_info(self, repo_name, pr_number):
        url = f"{self.github_api_base}/repos/{repo_name}/pulls/{pr_number}"
        headers = {"Authorization": f"token {self.github_token}"}
        async with self.session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.json()
            else:
                logger.error(f"Failed to fetch PR info for #{pr_number} in {repo_name}: {response.status}")
                return None

intents = discord.Intents.default()
intents.message_content = True
bot = GitHubBot(command_prefix='!', intents=intents)

app = Flask(__name__)

@bot.event
async def on_ready():
    logger.info(f'Bot {bot.user} has connected to Discord!')

@app.route('/webhook', methods=['POST'])
def webhook():
    signature = request.headers.get('X-Hub-Signature-256')
    if not signature:
        abort(400, 'X-Hub-Signature-256 header is missing.')
    
    payload = request.data
    secret = bot.github_webhook_secret.encode('utf-8')
    digest = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, f'sha256={digest}'):
        abort(401, 'Invalid signature.')
    
    data = request.json
    logger.info(f"Received webhook: {json.dumps(data)[:500]}...")
    
    asyncio.run_coroutine_threadsafe(bot.handle_github_event(data), bot.loop)
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
    await bot.sync_repos()
    await ctx.send("Sync completed.")

@bot.command(name='list_prs')
async def list_prs(ctx):
    """List all open PRs."""
    logger.info("List PRs command invoked")
    channel = bot.get_channel(bot.github_channel_id)
    open_prs = [thread for thread in channel.threads if thread.name.startswith("[") and "PR #" in thread.name and not thread.name.startswith("[CLOSED]")]
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