import os
import json
import tempfile
from fastapi import APIRouter, Request, Form, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse
from slack_sdk.signature import SignatureVerifier

from .utils import (
    parse_leave_request_llm, post_manager_leave_request,slack_client,
    extract_manager_id_from_mention,build_leave_confirmation,
    get_slack_user_timezone
)
from .config import settings

router = APIRouter()
verifier = SignatureVerifier(settings.SLACK_SIGNING_SECRET)

HANDLED_EVENT_IDS = set()

# GOOGLE_CREDS_DIR = os.path.join(os.path.dirname(__file__), "google_creds")

@router.post("/slack/events")
async def slack_events(request: Request):
    body = await request.body()
    if not verifier.is_valid_request(body=body, headers=request.headers):
        return JSONResponse(status_code=403, content={"msg": "Slack Verification Failed"})

    # Handle Slack interactive approvals (block_actions)
    form = await request.form()
    if "payload" in form:
        slack_payload = json.loads(form["payload"])
        if slack_payload.get("type") == "block_actions":
            action = slack_payload["actions"][0]
            if action["action_id"] == "approve_leave":
                value = json.loads(action['value'])
                user_id = value['uid']
                leave_dates = value.get('leave_dates', [])
                leave_type = value.get('leave_type', '')
                slack_client.chat_postMessage(
                    channel=user_id,
                    text=f"✅ Your leave ({', '.join(leave_dates)}) [{leave_type}] was approved! 🎉"
                )
                slack_client.chat_update(
                    channel=slack_payload["channel"]["id"],
                    ts=slack_payload["message"]["ts"],
                    text="✅ Approved.",
                    blocks=[]
                )
                return {"ok": True}
            elif action["action_id"] == "deny_leave":
                value = json.loads(action["value"])
                user_id = value["uid"]
                slack_client.chat_postMessage(
                    channel=user_id,
                    text="❌ Your leave request was denied by your manager."
                )
                slack_client.chat_update(
                    channel=slack_payload["channel"]["id"],
                    ts=slack_payload["message"]["ts"],
                    text="❌ Denied.",
                    blocks=[]
                )
                return {"ok": True}
        return JSONResponse(content={"msg": "No action."})

    payload = await request.json()
    event_id = payload.get("event_id")
    if event_id:
        if event_id in HANDLED_EVENT_IDS:
            print(f"[Deduplication] Already processed event_id={event_id}, skipping.")
            return {"ok": True}
        HANDLED_EVENT_IDS.add(event_id)


    if payload.get('challenge'):
        return JSONResponse(content={"challenge": payload['challenge']})

    if payload.get('event', {}).get('type') == 'app_mention':
        event = payload['event']
        user_id = event['user']
        user_message = event['text']

        leave_info = parse_leave_request_llm(user_id, user_message)
        if not leave_info:
            slack_client.chat_postMessage(
                channel=user_id,
                text="Sorry, I couldn't understand your leave request. Please try rephrasing."
            )
            return {"ok": True}

        # Manager mention must be present
        manager_mention = leave_info.get("manager_mention", "")
        manager_id = extract_manager_id_from_mention(manager_mention)
        
        if not manager_id:
            slack_client.chat_postMessage(
                channel=user_id,
                text="Please @-mention your manager in your leave request!"
            )
            return {"ok": True}
        if manager_id == user_id:
            slack_client.chat_postMessage(
                channel=user_id,
                text="You cannot approve your own leave. Please @-mention a different manager."
            )
            return {"ok": True}

        leave_dates = leave_info.get("leave_dates", [])
        leave_type = leave_info.get('leave_type', '')

        if not isinstance(leave_dates, list) or not leave_dates:
            slack_client.chat_postMessage(
                channel=user_id,
                text="Sorry, I couldn't parse the leave dates. Please specify clearly (e.g., '25-06-2025 and 27-06-2025' or 'next Monday and Thursday')."
            )
            return {"ok": True}
        # 🚩 ***SEND ONE APPROVAL REQUEST TO MANAGER ONLY!***
        post_manager_leave_request(user_id, leave_info, manager_id)

        # Confirmation to user
        msg = build_leave_confirmation(leave_dates, leave_type)
        slack_client.chat_postMessage(
            channel=user_id,
            text=msg
        )
        return {"ok": True}

    return JSONResponse(content={"msg": "Unhandled event."})

# --- /leave slash command handler ---
@router.post("/slack/slash")
async def slack_leave_slash(
    background_tasks: BackgroundTasks,
    request: Request,
    user_id: str = Form(...),
    text: str = Form(...),
):
    
    # Immediately return, Slack will show this as an ephemeral message
    background_tasks.add_task(process_leave_request_slash, user_id, text)
    return PlainTextResponse("Processing your leave request...")


def process_leave_request_slash(user_id, text):
    try:
        leave_info = parse_leave_request_llm(user_id, text)
        manager_mention = leave_info.get("manager_mention", "")
        manager_id = extract_manager_id_from_mention(manager_mention)

        if not manager_id or manager_id == user_id:
            slack_client.chat_postMessage(
                channel=user_id,
                text="❗Please @-mention your manager (as a clickable tag) and do not set yourself as the approver."
            )
            return
        
        # Send approval message to manager
        post_manager_leave_request(user_id, leave_info, manager_id)

        # Confirmation/feedback to user (as DM)
        leave_dates = leave_info["leave_dates"]
        leave_type = leave_info.get("leave_type", "")
        confirmation_msg = build_leave_confirmation(leave_dates, leave_type)

        slack_client.chat_postMessage(
            channel=user_id,
            text=confirmation_msg
        )
    except Exception as e:
        print(f"Slash background task error: {e}")
        try:
            slack_client.chat_postMessage(
                channel=user_id,
                text="⚠️ Error processing your leave request. Please try again or contact HR."
            )
        except:
            pass