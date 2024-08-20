# Discord GitHub Bot

## Description
This Discord bot integrates GitHub with Discord, providing real-time notifications and thread management for pull requests and pushes. It helps teams stay informed about their GitHub repository activities directly within their Discord server.

## Features
1. **Pull Request Notifications**: 
   - Creates a new thread in the designated Discord channel for each new pull request.
   - Thread title includes the PR number and title for easy reference.

2. **PR Comment Tracking**: 
   - Logs every comment made on a PR to its corresponding Discord thread.
   - Keeps all PR-related discussions organized and accessible.

3. **Automatic Thread Closure**: 
   - Automatically closes the Discord thread when the associated PR is closed on GitHub.
   - Helps maintain a clean and organized Discord channel.

4. **Environment Update Notifications**: 
   - Sends notifications to the main GitHub channel when specific branches (main, test, develop) are updated.
   - Keeps team members informed about important repository changes.

5. **Multi-Repository Support**: 
   - Capable of connecting and monitoring multiple GitHub repositories.
   - Centralizes notifications from various projects in one Discord server.

## Technologies Used
- **Python**: The primary programming language used for developing the bot.
- **discord.py**: A modern, easy to use, feature-rich Python library for interacting with the Discord API.
- **Flask**: A lightweight WSGI web application framework used to handle incoming webhook events from GitHub.
- **Requests**: A simple HTTP library for Python, used for making API calls to GitHub if needed.
- **GitHub Webhooks**: Used to send repository events to our bot.
- **Render**: A unified cloud platform used for deploying and hosting the bot.

## Setup and Deployment
(Include basic setup instructions here, or link to a more detailed guide)

## Configuration
(Explain any configuration options, environment variables, etc.)

## Contributing
We welcome contributions to improve the Discord GitHub Bot! Please feel free to submit issues, fork the repository and send pull requests!