import openai
import json
import re
import time
from datetime import date
from slack_sdk import WebClient
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
from ics import Calendar, Event
from .prompt_helper import get_llm_leave_system_prompt 


from .config import settings

slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)
openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

APPROVAL_EMOJI = {
    "vacation": "🌴",
    "sick": "🤒",
    "personal": "🏡",
    "default": "😊"
}

USER_CACHE = {"users": [], "last_updated": 0}

def parse_leave_request_llm(user_id: str, user_message: str):
    user_tz = get_slack_user_timezone(user_id, slack_client)
    if user_tz is None:
        user_tz = 'UTC'

    system_prompt =system_prompt = get_llm_leave_system_prompt(user_tz)
    response = openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        max_tokens=512,
        temperature=0.0
    )
    # Updated for new API
    try:
        import json
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print("LLM Parse error:", e, response)
        return {}

def post_manager_leave_request(user_id, leave_info, manager_id):
    leave_type = (leave_info.get('leave_type') or "not specified").capitalize()
    leave_dates = leave_info.get('leave_dates', [])
    leave_reason = leave_info.get('leave_reason', '')
    dates_str = (
        leave_dates[0] if len(leave_dates) == 1
        else f"{leave_dates[0]} and {leave_dates[1]}" if len(leave_dates) == 2
        else (", ".join(leave_dates[:-1]) + f", and {leave_dates[-1]}" if leave_dates else "")
    )
    text = (
        f"*Leave request* from <@{user_id}>:\n"
        f"*Type*: {leave_type}\n"
        f"*Dates*: {dates_str}\n"
        f"*Reason*: {leave_reason or '_Not specified_'}"
    )
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": "approve_leave",
                "value": json.dumps({
                    "uid": user_id,
                    "leave_dates": leave_dates,
                    "leave_type": leave_type,
                    "leave_reason": leave_reason
                })
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Deny"},
                "style": "danger",
                "action_id": "deny_leave",
                "value": json.dumps({
                    "uid": user_id
                })
            }
        ]}
    ]
    slack_client.chat_postMessage(
        channel=manager_id,
        text=f"Leave request from <@{user_id}>",
        blocks=blocks
    )

def set_slack_ooo(user_id: str, leave_info: dict):
    slack_client.users_profile_set(
        user=user_id,
        profile={
            "status_text": f"OOO until {leave_info.get('leave_dates')}",
            "status_emoji": ":palm_tree:",
            "status_expiration": 0,
        }
    )

def create_gcal_ooo_event(leave_info: dict, gcal_email: str, google_creds_dir: str):
    creds_file = f"{google_creds_dir}/token.json"
    creds = Credentials.from_authorized_user_file(creds_file, ['https://www.googleapis.com/auth/calendar'])
    service = build('calendar', 'v3', credentials=creds)
    # Parse simple date ranges: 2024-06-15 or 2024-06-15 to 2024-06-18
    dates = leave_info.get('leave_dates').split(' to ')
    start_date = dates[0]
    end_date = dates[1] if len(dates) > 1 else dates[0]
    # Google Calendar end date is exclusive, so add 1 day if single-day
    if start_date == end_date:
        end_date_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        end_date = end_date_dt.strftime("%Y-%m-%d")
    event = {
        'summary': 'Out of Office',
        'description': leave_info.get('leave_reason', ''),
        'start': {'date': start_date, 'timeZone': 'UTC'},
        'end': {'date': end_date, 'timeZone': 'UTC'},
        'transparency': 'opaque',
        'visibility': 'default',
    }
    service.events().insert(calendarId=gcal_email, body=event).execute()

def lookup_slack_id_by_name(name: str) -> str:
    """Find Slack user ID by their real name or display name, returns first match or None."""
    # This will call users.list API (requires users:read permission on the bot)
    resp = slack_client.users_list()
    for user in resp['members']:
        # 'real_name' is full name, 'profile.display_name' is Slack display
        if not user.get('deleted') and (name.lower() in user['real_name'].lower() or name.lower() in user['profile'].get('display_name', '').lower()):
            return user['id']
    return None

def create_ics_event(summary, start_date, end_date, description):
    c = Calendar()
    e = Event()
    e.name = summary
    e.begin = start_date
    # If single-day, add 1 day to end (Google/Outlook expects exclusive end)
    from datetime import datetime, timedelta
    try:
        dt_start = datetime.strptime(start_date, "%Y-%m-%d")
        dt_end = datetime.strptime(end_date, "%Y-%m-%d")
    except Exception:
        # fallback: leave unchanged, some date parsing may be needed
        dt_start = dt_end = None
    if dt_end and dt_start and dt_end == dt_start:
        dt_end = dt_start + timedelta(days=1)
        e.end = dt_end.strftime("%Y-%m-%d")
    else:
        e.end = end_date
    e.description = description
    c.events.add(e)
    return str(c)

def extract_user_ids(text):
    """
    Extract Slack user IDs mentioned via <@Uxxxxxxx>.
    Returns: list of user IDs (strings).
    """
    return re.findall(r"<@([A-Z0-9]+)>", text)

def extract_manager_id_from_mention(mention_str):
    """
    Extract Slack User ID from either a canonical Slack mention <@U12345>
    or (if slack_client is given) a plain @username or display_name.

    Returns user_id or None.
    """
    if not mention_str:
        return None

    # 1. Try canonical Slack mention: <@U12345>
    m = re.search(r"<@([A-Z0-9]+)>", mention_str)
    if m:
        return m.group(1)

    # 2. Fallback: @username or display name
    if slack_client:
        users = get_cached_slack_users(slack_client)
        username_match = re.match(r"@(\w+)", mention_str)
        username = username_match.group(1) if username_match else None

        for user in users:
            # Match username (e.g. @arajadurai)
            if username and (user.get("name") == username or user.get("profile", {}).get("display_name") == username):
                return user["id"]
            # Match plain text mention with real name (e.g. "Priya")
            if mention_str.strip() == user.get("real_name", ""):
                return user["id"]
    
    return None

def get_emoji_for_type(leave_type: str) -> str:
    return APPROVAL_EMOJI.get((leave_type or "").lower(), APPROVAL_EMOJI["default"])

def build_leave_confirmation(dates, leave_type):
    # Use lower-case for matching
    lt = (leave_type or "default").lower()
    emoji = get_emoji_for_type(leave_type)
    if not dates:
        return f"Your leave request has been forwarded to your manager. {emoji}🤝"
    elif len(dates) == 1:
        return f"Your leave request for {dates[0]} has been forwarded to your manager for approval. {emoji}🤝"
    elif len(dates) == 2:
        return f"Your leave request for {dates[0]} and {dates[1]} has been forwarded to your manager for approval. {emoji}🤝"
    else:
        all_but_last = ", ".join(dates[:-1])
        return f"Your leave request for {all_but_last}, and {dates[-1]} has been forwarded to your manager for approval. {emoji}🤝"
    
def get_slack_user_timezone(user_id, slack_client: WebClient):
    """
    Returns the user's IANA timezone string (e.g. 'Asia/Kolkata') given their Slack user ID,
    or None if it cannot be determined.
    """
    try:
        response = slack_client.users_info(user=user_id)
        user = response['user']
        return user.get('tz')  # Example: 'Asia/Kolkata', 'America/Los_Angeles'
    except Exception as e:
        print(f"Unable to fetch user info or timezone for user {user_id}:", e)
        return None
    
def get_cached_slack_users(slack_client, cache_seconds=600):
    """
    Get list of users from cache, or refresh if cache is old or empty.
    - Only calls Slack API once per 'cache_seconds' (default 10 min).
    - On error or ratelimit, returns last known cached list, never blocks.
    """
    now = time.time()
    # Only update from API when past cache_seconds since last update
    if now - USER_CACHE["last_updated"] > cache_seconds or not USER_CACHE["users"]:
        try:
            print("Fetching users from Slack API...")
            users_resp = slack_client.users_list()
            if users_resp.get("ok"):
                USER_CACHE["users"] = users_resp["members"]
                USER_CACHE["last_updated"] = now
            else:
                print(f"Slack users_list error: {users_resp.get('error')}")
        except Exception as e:
            print(f"Slack users_list API call failed: {e}")
            # Fallback, serve the last cached version anyway
    return USER_CACHE["users"]