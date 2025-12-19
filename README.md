# FlexiOff

**FlexiOff** is a FastAPI-based SmartLeaveBot that leverages OpenAI LLM to deeply understand natural language leave requests. Leave requests are routed to a manager (specified by their name in the Slack request) for approval, Out-of-Office status is automated, and Google Calendar integration is included.

---

## Required Environment Variables

Set these system environment variables before running the app:

| Variable Name        | Description                                                             |
|----------------------|-------------------------------------------------------------------------|
| `SLACK_BOT_TOKEN`      | OAuth bot token for your Slack app (starts with `xoxb-...`)            |
| `SLACK_SIGNING_SECRET` | Signing secret for Slack event/interactivity requests                  |
| `OPENAI_API_KEY`       | OpenAI API key (for GPT-4)                                             |
| `EMPLOYEE_GCAL_EMAIL`  | The employee’s Google Calendar email address (used for OOO entries)    |

> With manager name extraction, you **do not** need to set a single `MANAGER_USER_ID`. The manager is specified dynamically in the leave request.

---

## Required Slack App OAuth Scopes

Your Slack bot/app needs the following [OAuth Scopes](https://api.slack.com/scopes):

| Scope                  | Why                                                             |
|------------------------|-----------------------------------------------------------------|
| `chat:write`           | Send messages (to users, channels, etc)                         |
| `chat:write.public`    | (Optional) DM users with whom the bot isn't already in a conversation |
| `users:read`           | To look up Slack user IDs from manager names                    |
| `users:read.email`     | (Optional) Lookup user by email (for robust matching)           |
| `users.profile:write`  | Update employee Slack status (OOO)                              |
| `im:write`             | DM managers or employees                                        |

In the [Slack app config](https://api.slack.com/apps), add these under **OAuth & Permissions → Bot Token Scopes**.

---

### Event Subscriptions & Interactivity

- Enable **event subscriptions** for `app_mention`.
- Set the **Request URL** for both Events and Interactivity to:

---

## Google Calendar

- Enable the [Google Calendar API](https://console.developers.google.com/apis/api/calendar.googleapis.com/overview) for your project.
- Place your authorized `credentials.json` and `token.json` in ./app/google_creds/ directory.

---

## Running the App

**With the provided Makefile:**

- make install
- make run

---

## Usage

@FlexiOff I need vacation next Monday and Tuesday, please send to manager Priya Singh.