import json
import asyncio
import re
import requests
from datetime import datetime
from collections import Counter
from telethon import TelegramClient, events
from telethon.tl.types import PeerUser, PeerChat, PeerChannel, MessageEntityMentionName
from telethon.tl import functions
from telethon.tl.functions.users import GetFullUserRequest

CONFIG_FILE = "config.json"

def is_meaningless(text):
    cleaned = re.sub(r'[\s\U0001F600-\U0010FFFF]', '', text)
    if not cleaned:
        return True
    letters = [c for c in cleaned if c.isalpha()]
    if not letters:
        return True
    vowels = set('аеёиоуыэюяaeiou')
    vowel_count = sum(1 for c in letters if c.lower() in vowels)
    if vowel_count / len(letters) < 0.1:
        return True
    cons_max = 0
    cur = 0
    for c in letters:
        if c.lower() not in vowels:
            cur += 1
            cons_max = max(cons_max, cur)
        else:
            cur = 0
    if cons_max >= 5:
        return True
    rows = [
        set('qwertyuiop'), set('asdfghjkl'), set('zxcvbnm'),
        set('йцукенгшщзхъ'), set('фывапролджэ'), set('ячсмитьбю'),
    ]
    for row in rows:
        row_letters = [c.lower() for c in letters if c.lower() in row]
        if len(row_letters) >= 3 and len(row_letters) / len(letters) > 0.8:
            return True
    return False

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

API_ID = config["api_id"]
API_HASH = config["api_hash"]
PHONE = config["phone"]
PUTER_TOKEN = config["puter_token"]
PUTER_API = "https://api.puter.com"

chat_history = {}
chat_profiles = {}
tracked_user = None
tracked_user_id = None
TRACK_USERNAME = "@wIw11111"
AI_MODEL = "claude-opus-4-8"

async def tell_me(client, text):
    if client and hasattr(client, 'me_id') and client.me_id:
        await client.send_message(client.me_id, text)

SYSTEM_PROMPT = """You are the user's personal AI secretary. The user's name is {user_name}. The user is busy or sleeping — you manage their Telegram account.

CRITICAL: ALWAYS reply in the EXACT SAME LANGUAGE as the person writing. NEVER switch languages.

CHAT PROFILE:
{chat_profile}

YOUR RULES:
1. You MUST write EXACTLY like {user_name} writes in this chat. Match their style, length, tone, and word choices exactly.
2. Private DMs: take messages, fight back if insulted, be friendly if friendly
3. Groups: only reply when mentioned (@{user_name}) or replied to. Never reveal you're AI
4. "скажи ему" / "tell him" → message is for {user_name}, take it
5. Block users who say "block" / "blok" / "заблокируй"
6. Adapt to each conversation flow. Read the context history below before responding."""

BOSS_PROMPT = """You are {user_name}'s personal AI secretary. The user is talking to you in their private Saved Messages chat.

CRITICAL: Always reply in the SAME LANGUAGE as {user_name} writes to you.

You report about the tracked person ({tracked_name}) - their online status, messages, activity.
You can answer questions about what's happening with tracked users, conversations, and anything else.

Tracked person info:
- Name: {tracked_name}
- Stats: {tracked_stats}

Write like a real secretary talking to their boss. Be direct, helpful, honest. Use short messages."""

TRACKING_PROMPT = """You are {user_name}'s secretary. Report to your boss ({user_name}) about the person they are tracking ({tracked_name}).

Write like a real assistant talking to their boss. Be direct, natural, and concise. Use the same language as {user_name} would use.

Recent events about {tracked_name}:
{events}

Give a brief summary of what happened - when they came online, what they wrote, where."""

def ask_puter(messages, model=AI_MODEL):
    payload = {
        "interface": "puter-chat-completion",
        "driver": "ai-chat",
        "method": "complete",
        "args": {"messages": messages, "model": model},
        "test_mode": False
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {PUTER_TOKEN}"
    }
    r = requests.post(f"{PUTER_API}/drivers/call", json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    result = r.json()
    content = result["result"]["message"]["content"]
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return content

def get_code():
    import time
    print("Waiting for code in code.txt...")
    while True:
        try:
            with open("code.txt", "r") as f:
                code = f.read().strip()
            if code:
                open("code.txt", "w").write("")
                return code
        except FileNotFoundError:
            pass
        time.sleep(1)

def detect_language(texts):
    kk_words = {'кел', 'бара', 'жол', 'үй', 'қазір', 'келемін', 'жарайды', 'майли', 'керасаг', 'керасақ', 'қайда', 'не', 'қалай', 'болады', 'жоқ', 'иә', 'рахмет', 'кешір', 'ал', 'бер', 'қара'}
    uz_words = {'kel', 'bor', 'yo\'l', 'uy', 'hozir', 'kelyapman', 'mayli', ' kerak', 'qani', 'nima', 'qanday', 'bo\'ladi', 'yo\'q', 'ha', 'rahmat', 'kechir', 'ol', 'ber', 'qara'}
    scores = {'uz': 0, 'kk': 0, 'ru': 0, 'en': 0}
    for t in texts:
        lower = t.lower()
        words = set(lower.split())
        scores['kk'] += sum(2 for w in words if w in kk_words)
        scores['uz'] += sum(2 for w in words if w in uz_words)
        if 'ў' in lower or 'қ' in lower or 'ғ' in lower or 'ҳ' in lower:
            scores['uz'] += 1
        if 'ү' in lower or 'ұ' in lower or 'ә' in lower or 'ң' in lower:
            scores['kk'] += 3
        if 'ы' in lower or 'ъ' in lower or 'э' in lower or 'ё' in lower:
            scores['ru'] += 2
        en_words = sum(1 for w in words if w in 'the is are was were has have been will would')
        ru_words = sum(1 for w in words if w in 'что это как где когда почему зачем')
        scores['en'] += en_words
        scores['ru'] += ru_words
        for c in lower:
            if 'a' <= c <= 'z':
                scores['en'] += 0.5
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'unknown'

async def analyze_chat(client, chat_id, is_group=False, chat_name="", my_id=None):
    try:
        my_texts = []
        all_texts = []
        names = []
        count = 0
        async for m in client.iter_messages(chat_id):
            if m.text:
                all_texts.append({"text": m.text, "sender_id": m.sender_id})
                if my_id and m.sender_id == my_id:
                    my_texts.append(m.text)
                if is_group and m.sender_id:
                    try:
                        s = await m.get_sender()
                        if s:
                            names.append(s.first_name or "")
                    except:
                        pass
                count += 1
                if count % 500 == 0:
                    print(f"    [{chat_name[:25]:25s}] loaded {count} messages...")
        if not all_texts:
            return {"style": "unknown", "language": "unknown", "tone": "neutral", "my_style": "unknown"}
        user_texts = my_texts if my_texts else [t["text"] for t in all_texts[:50]]
        lang = detect_language([t["text"] for t in all_texts[:100]])
        avg_len = sum(len(t) for t in user_texts) / max(len(user_texts), 1)
        if avg_len < 20:
            tone = "short and casual"
        elif avg_len < 50:
            tone = "normal"
        else:
            tone = "detailed"
        caps_ratio = sum(1 for t in user_texts if t == t.upper() and len(t) > 3) / max(len(user_texts), 1)
        if caps_ratio > 0.1:
            tone += ", loud"
        samples = user_texts[-5:] if len(user_texts) >= 5 else user_texts
        my_style_samples = " | ".join(f'"{s}"' for s in samples[:5])
        unique_names = len(set(n for n in names if n))
        profile = {
            "style": f"{'group' if is_group else 'dm'} chat",
            "language": lang,
            "tone": tone,
            "my_style": my_style_samples,
            "my_msg_count": len(my_texts),
            "participants": unique_names,
            "sample_count": len(all_texts)
        }
        return profile
    except Exception as e:
        return {"style": "unknown", "language": "unknown", "tone": "neutral", "my_style": "unknown", "my_msg_count": 0}

def profile_to_text(profile, chat_name):
    if not profile or profile.get("style") == "unknown":
        return f"Chat: {chat_name}. No analysis available yet."
    result = f"Chat: {chat_name} | Language: {profile['language']} | Tone: {profile['tone']}"
    if profile.get("my_style") and profile["my_style"] != "unknown":
        result += f"\nUser's writing style in this chat: {profile['my_style']}"
    return result

async def refresh_profiles(client, me, dialogs):
    print("\n=== ANALYZING ALL CHATS ===")
    for d in dialogs:
        cid = d.id
        if d.is_user:
            profile = await analyze_chat(client, cid, is_group=False, chat_name=d.name, my_id=me.id)
        elif d.is_group:
            profile = await analyze_chat(client, cid, is_group=True, chat_name=d.name, my_id=me.id)
        else:
            continue
        chat_profiles[cid] = profile
        print(f"  [{d.name[:30]:30s}] lang={profile['language']} tone={profile['tone']}")
    print("============================\n")
    chat_profiles['_last_refresh'] = datetime.now()

async def periodic_refresh(client, me, dialogs, interval=1800):
    while True:
        await asyncio.sleep(interval)
        print(f"\n[Auto-refresh] Re-analyzing chats at {datetime.now().strftime('%H:%M')}")
        dialogs = await client.get_dialogs()
        await refresh_profiles(client, me, dialogs)

async def report_to_me(client, me, tracked_name, events_list):
    if not events_list:
        return
    events_text = "\n".join(events_list[-10:])
    prompt = TRACKING_PROMPT.format(user_name=me.first_name, tracked_name=tracked_name, events=events_text)
    try:
        reply = ask_puter([{"role": "user", "content": prompt}])
        await tell_me(client, reply)
    except Exception as e:
        await tell_me(client, f"[{tracked_name}] {events_list[-1]}")

async def resolve_tracked_user(client):
    global tracked_user, tracked_user_id
    username = TRACK_USERNAME.lstrip("@")
    try:
        tracked_user = await client.get_entity(username)
        tracked_user_id = tracked_user.id
        name = tracked_user.first_name or username
        await tell_me(client, f"Boss, men {name} (@{username}) ni kuzatishni boshladim")
        return True
    except Exception as e:
        print(f"[TRACK ERROR] Could not find user {TRACK_USERNAME}: {e}")
        return False

tracked_stats = {
    "online_count": 0, "offline_count": 0,
    "msg_count": 0, "groups_seen": set(),
    "last_online": None, "first_seen": datetime.now(),
    "last_profile_name": None, "last_profile_username": None,
    "event_buffer": []
}

async def check_gifts(client, me):
    if not tracked_user_id:
        return
    try:
        full = await client(GetFullUserRequest(id=tracked_user_id))
        for attr_name in dir(full):
            if 'gift' in attr_name.lower() or 'star' in attr_name.lower():
                val = getattr(full, attr_name)
                if val:
                    name = tracked_user.first_name or TRACK_USERNAME
                    await tell_me(client, f"Boss, {name} da gift/podarka topildi: {attr_name} = {val}")
    except Exception as e:
        pass

async def setup_tracking(client, me):
    if not tracked_user_id:
        return

    tracked_stats["last_profile_name"] = tracked_user.first_name
    tracked_stats["last_profile_username"] = tracked_user.username
    tracked_name = tracked_user.first_name or TRACK_USERNAME

    report_lock = asyncio.Lock()
    last_report_time = 0

    async def flush_report():
        nonlocal last_report_time
        async with report_lock:
            if tracked_stats["event_buffer"]:
                now = datetime.now().timestamp()
                if now - last_report_time > 60:
                    events = list(tracked_stats["event_buffer"])
                    tracked_stats["event_buffer"].clear()
                    last_report_time = now
                    asyncio.create_task(report_to_me(client, me, tracked_name, events))

    @client.on(events.UserUpdate)
    async def status_handler(event):
        if event.user_id == tracked_user_id:
            from telethon.tl.types import UserStatusOnline, UserStatusOffline
            s = event.status
            if isinstance(s, UserStatusOnline):
                tracked_stats["online_count"] += 1
                tracked_stats["last_online"] = datetime.now()
                tracked_stats["event_buffer"].append(f"Came online (time #{tracked_stats['online_count']})")
            elif isinstance(s, UserStatusOffline):
                tracked_stats["offline_count"] += 1
                tracked_stats["event_buffer"].append(f"Went offline")
            await flush_report()

    @client.on(events.NewMessage)
    async def profile_check(event):
        if event.sender_id == tracked_user_id:
            tracked_stats["msg_count"] += 1
            try:
                u = await event.get_sender()
                if u.first_name != tracked_stats["last_profile_name"] or u.username != tracked_stats["last_profile_username"]:
                    old_name = tracked_stats["last_profile_name"]
                    tracked_stats["last_profile_name"] = u.first_name
                    tracked_stats["last_profile_username"] = u.username
                    tracked_stats["event_buffer"].append(f"Changed name: {old_name} -> {u.first_name}")
                    await flush_report()
            except:
                pass

    await check_gifts(client, me)

    async def gift_poller():
        await asyncio.sleep(300)
        while True:
            await check_gifts(client, me)
            await asyncio.sleep(3600)

    asyncio.create_task(gift_poller())

    async def daily_report():
        while True:
            await asyncio.sleep(3600)
            now = datetime.now()
            if now.hour == 23 and now.minute < 5:
                total_online = tracked_stats["online_count"]
                total_msg = tracked_stats["msg_count"]
                total_groups = len(tracked_stats["groups_seen"])
                msg = f"Boss, kun yakuni bo'yicha {tracked_name}: {total_online} marta online bo'ldi, {total_msg} ta xabar yozdi, {total_groups} ta guruhda aktiv edi"
                await tell_me(client, msg)

    asyncio.create_task(daily_report())

async def handle_group_message(event, client, me, text, chat):
    sender = await event.get_sender()
    sender_name = sender.first_name or "Unknown"
    chat_id = event.chat_id

    is_mentioned = False
    if event.mentioned or (event.message and event.message.entities):
        for e in event.message.entities or []:
            if isinstance(e, MessageEntityMentionName) and e.user_id == me.id:
                is_mentioned = True
            elif hasattr(e, 'offset') and hasattr(e, 'length'):
                mention = text[e.offset:e.offset+e.length]
                if me.username and mention.lower() == f"@{me.username.lower()}":
                    is_mentioned = True

    is_reply_to_me = False
    if event.message and event.message.reply_to:
        try:
            replied = await event.message.get_reply_message()
            if replied and replied.sender_id == me.id:
                is_reply_to_me = True
        except:
            pass

    if not is_mentioned and not is_reply_to_me:
        if tracked_user_id and sender.id == tracked_user_id:
            tracked_stats["groups_seen"].add(chat.title or "Unknown")
            tracked_stats["event_buffer"].append(f"Wrote in [{chat.title}]: {text[:100]}")
            tracked_stats["msg_count"] += 1
            async with asyncio.Lock():
                pass
            try:
                async def report_group():
                    if tracked_stats["event_buffer"]:
                        events = list(tracked_stats["event_buffer"])
                        tracked_stats["event_buffer"].clear()
                        await report_to_me(client, me, tracked_user.first_name or TRACK_USERNAME, events)
                asyncio.create_task(report_group())
            except:
                pass
        return

    context = []
    async for m in client.iter_messages(chat_id, limit=15):
        if m.text:
            try:
                s = await m.get_sender()
                n = s.first_name if s else "Unknown"
                context.insert(0, f"[{n}]: {m.text}")
            except:
                context.insert(0, f"[?]: {m.text}")

    profile = chat_profiles.get(chat_id, {})
    profile_text = profile_to_text(profile, chat.title or "Unknown Group")
    context_str = "\n".join(context[-10:])

    prompt = SYSTEM_PROMPT.format(user_name=me.first_name, chat_profile=profile_text)
    prompt += f"\n\nGROUP: {chat.title}\n"
    prompt += f"CONTEXT (last messages):\n{context_str}\n\n"
    prompt += f"{sender_name} addressed you: \"{text}\"\n"
    prompt += f"Reply in the language and style of this chat."

    messages = [{"role": "system", "content": prompt}]
    try:
        reply = ask_puter(messages)
        await event.reply(reply)
        print(f"[{chat.title}] {sender_name}: {text}")
        print(f"[Bot]: {reply}")
    except Exception as e:
        print(f"[Group Error] {chat.title}: {e}")

async def handle_dm_message(event, client, me, text):
    sender = await event.get_sender()
    sender_name = sender.first_name or "Unknown"
    user_id = event.peer_id.user_id

    if tracked_user_id and user_id == tracked_user_id:
        tracked_stats["event_buffer"].append(f"Sent you DM: {text[:100]}")
        asyncio.create_task(
            report_to_me(client, me, tracked_user.first_name or TRACK_USERNAME, [f"Sent you DM: {text[:100]}"])
        )

    if not text or is_meaningless(text):
        print(f"[{sender_name}]: {text} (skipped)")
        return

    print(f"[DM {sender_name}]: {text}")

    if user_id not in chat_history:
        chat_history[user_id] = []

    chat_history[user_id].append({"role": "user", "content": text})
    if len(chat_history[user_id]) > 50:
        chat_history[user_id] = chat_history[user_id][-50:]

    profile = chat_profiles.get(user_id, {})
    profile_text = profile_to_text(profile, sender_name)

    system_prompt = SYSTEM_PROMPT.format(user_name=me.first_name, chat_profile=profile_text)
    system_prompt += "\n\nCHAT TYPE: Private DM."
    messages = [{"role": "system", "content": system_prompt}] + chat_history[user_id]

    try:
        reply = ask_puter(messages)
        if not reply or (len(reply) < 2 and reply.strip() in {'.', ',', '!', '?', '...'}):
            print(f"[DM {sender_name}]: empty reply, skipping")
            return
        chat_history[user_id].append({"role": "assistant", "content": reply})
        await event.reply(reply)
        print(f"[Bot]: {reply}")
    except Exception as e:
        print(f"[DM Error] {sender_name}: {e}")

    block_words = ['block', 'blok', 'блок', 'заблокируй']
    if any(kw in text.lower() for kw in block_words):
        try:
            await client(functions.contacts.BlockRequest(id=user_id))
            print(f"[Blocked] {sender_name} ({user_id})")
        except Exception as e:
            print(f"[Block Error] {e}")

Boss_chat_history = []

async def handle_boss_message(event, client, me, text):
    global Boss_chat_history
    print(f"[Boss]: {text}")
    Boss_chat_history.append({"role": "user", "content": text})
    if len(Boss_chat_history) > 30:
        Boss_chat_history = Boss_chat_history[-30:]

    tracked_name = tracked_user.first_name if tracked_user else TRACK_USERNAME
    stats = f"Online today: {tracked_stats['online_count']}, Messages: {tracked_stats['msg_count']}, Groups: {len(tracked_stats['groups_seen'])}"
    prompt = BOSS_PROMPT.format(user_name=me.first_name, tracked_name=tracked_name, tracked_stats=stats)
    messages = [{"role": "system", "content": prompt}] + Boss_chat_history
    try:
        reply = ask_puter(messages)
        Boss_chat_history.append({"role": "assistant", "content": reply})
        await event.reply(reply)
        print(f"[Secretary]: {reply}")
    except Exception as e:
        print(f"[Boss Error]: {e}")

async def main():
    client = TelegramClient("session", API_ID, API_HASH)
    client.me_id = None
    await client.start(phone=PHONE, code_callback=get_code)
    me = await client.get_me()
    client.me_id = me.id
    print(f"\nLogged in as: {me.first_name} (@{me.username})")

    dialogs = await client.get_dialogs()
    print(f"Total dialogs: {len(dialogs)}")

    await refresh_profiles(client, me, dialogs)

    if await resolve_tracked_user(client):
        await setup_tracking(client, me)

    asyncio.create_task(periodic_refresh(client, me, dialogs, 1800))

    @client.on(events.NewMessage)
    async def handler(event):
        text = (event.text or "").strip()
        if not text:
            return

        is_self_chat = isinstance(event.peer_id, PeerUser) and event.peer_id.user_id == me.id

        if is_self_chat:
            await handle_boss_message(event, client, me, text)
            return

        if event.out:
            return

        if isinstance(event.peer_id, PeerUser):
            await handle_dm_message(event, client, me, text)
        elif isinstance(event.peer_id, (PeerChat, PeerChannel)):
            chat = await event.get_chat()
            await handle_group_message(event, client, me, text, chat)

    print("Bot is running. You can chat with me in Saved Messages!\n")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
