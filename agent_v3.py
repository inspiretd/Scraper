import json
import asyncio
import re
import os
import time
import requests
from datetime import datetime
from collections import defaultdict
from telethon import TelegramClient, events
from telethon.tl.types import PeerUser, PeerChat, PeerChannel, MessageEntityMentionName, UserStatusOnline, UserStatusOffline
from telethon.tl import functions
from telethon.tl.functions.users import GetFullUserRequest

CONFIG_FILE = "config.json"
MEMORY_DIR = "agent_memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()
API_ID = config["api_id"]
API_HASH = config["api_hash"]
PHONE = config["phone"]
PUTER_TOKEN = config["puter_token"]
PUTER_API = "https://api.puter.com"
AI_MODEL = "claude-opus-4-8"

# ─────────────────────────────────────────────
# 0. JSON File Helpers
# ─────────────────────────────────────────────
def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def now_ts():
    return int(time.time())

# ─────────────────────────────────────────────
# 1. MEMORY SYSTEM
# ─────────────────────────────────────────────
# Short-term memory (per chat, in-memory)
stm = defaultdict(lambda: {"messages": [], "last_seen": 0})
# Long-term memory (per user, file-backed)
ltm_path = os.path.join(MEMORY_DIR, "user_profiles.json")
ltm_cache = read_json(ltm_path, {})
# Episodic memory
episodic_path = os.path.join(MEMORY_DIR, "episodic_memory.json")
episodic = read_json(episodic_path, [])
# Semantic memory
semantic_path = os.path.join(MEMORY_DIR, "semantic_memory.json")
semantic = read_json(semantic_path, {"best_style": "adaptive", "avoid_topics": [], "trust_default": 50})
# Dynamic instructions
dyn_inst_path = os.path.join(MEMORY_DIR, "dynamic_instructions.txt")
if not os.path.exists(dyn_inst_path):
    with open(dyn_inst_path, "w", encoding="utf-8") as f:
        f.write("No additional instructions yet.\n")

def save_ltm():
    write_json(ltm_path, ltm_cache)

def save_episodic():
    write_json(episodic_path, episodic[-200:])

def save_semantic():
    write_json(semantic_path, semantic)

def get_profile(user_id):
    uid = str(user_id)
    if uid not in ltm_cache:
        ltm_cache[uid] = {
            "language": "unknown",
            "interests": [],
            "style": "unknown",
            "relationship_score": 50,
            "interaction_count": 0,
            "last_seen": 0,
            "positive_count": 0,
            "negative_count": 0,
            "emotion_history": []
        }
    return ltm_cache[uid]

def update_relationship(user_id, delta, reason=""):
    prof = get_profile(user_id)
    prof["relationship_score"] = max(0, min(100, prof["relationship_score"] + delta))
    prof["interaction_count"] += 1
    if delta > 0:
        prof["positive_count"] += 1
    elif delta < 0:
        prof["negative_count"] += 1
    prof["last_seen"] = now_ts()
    save_ltm()
    if abs(delta) >= 10:
        add_episodic(user_id, f"Relationship change: {delta} ({reason})", abs(delta))

def add_episodic(user_id, event, importance=5):
    episodic.append({
        "ts": now_ts(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "user_id": user_id,
        "event": event,
        "importance": min(importance, 10)
    })
    save_episodic()

def add_stm(user_id, role, text):
    stm[user_id]["messages"].append({"role": role, "text": text, "ts": now_ts()})
    stm[user_id]["last_seen"] = now_ts()
    if len(stm[user_id]["messages"]) > 100:
        stm[user_id]["messages"] = stm[user_id]["messages"][-100:]

def get_stm_context(user_id, limit=10):
    msgs = stm[user_id]["messages"][-limit:]
    return "\n".join(f"[{m['role']}]: {m['text']}" for m in msgs)

def get_relationship_label(score):
    if score >= 80: return "trusted"
    if score >= 60: return "friendly"
    if score >= 40: return "neutral"
    if score >= 20: return "suspicious"
    return "dangerous"

# ─────────────────────────────────────────────
# 2. EMOTION DETECTION
# ─────────────────────────────────────────────
def detect_emotion(text):
    angry_words = {'idiot', 'fuck', 'suck', 'bastard', 'tupoy', 'baholni', 'banan', 'ebal', 'ebany', 'huinya', 'dolboyob', 'pidor', 'xuy', 'blya', 'nahuy', 'ebeni', 'musor', 'tentak', 'ahmoq', 'sikim', 'qanjiq', 'jalyab', 'jump', 'баран', 'лох', 'тупой', 'ебан', 'хуй', 'бля', 'нах', 'пидор', 'гандон'}
    sad_words = {'afsus', 'xin', 'g\'amgin', 'zerikdim', 'hafa', ' грустно', 'печаль', 'уныло', 'грущу'}
    happy_words = {'haha', 'lol', 'хаха', 'круто', 'отлично', 'супер', 'rahmat', 'yaxshi', 'zo\'r', 'рад', 'весело'}
    lower = text.lower()
    has_angry = sum(1 for w in angry_words if w in lower)
    has_sad = sum(1 for w in sad_words if w in lower)
    has_happy = sum(1 for w in happy_words if w in lower)
    if has_angry > has_happy and has_angry > has_sad:
        return "angry", min(0.99, 0.6 + has_angry * 0.1)
    if has_sad > has_happy:
        return "sad", min(0.95, 0.5 + has_sad * 0.15)
    if has_happy > 0:
        return "happy", min(0.95, 0.5 + has_happy * 0.1)
    return "neutral", 0.5

# ─────────────────────────────────────────────
# 3. AI FUNCTIONS
# ─────────────────────────────────────────────
def ask_puter(messages, model=AI_MODEL, timeout=120):
    payload = {
        "interface": "puter-chat-completion",
        "driver": "ai-chat",
        "method": "complete",
        "args": {"messages": messages, "model": model},
        "test_mode": False
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {PUTER_TOKEN}"}
    r = requests.post(f"{PUTER_API}/drivers/call", json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    result = r.json()
    content = result["result"]["message"]["content"]
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return content

def ask_agent(system_prompt, user_message):
    """Ask AI with structured system prompt, return text response."""
    try:
        return ask_puter([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ])
    except Exception as e:
        return f"[ERROR: {e}]"

def ask_with_tools(system_prompt, user_message):
    """Ask AI to reason and return JSON tool call."""
    prompt = system_prompt + "\n\nYou MUST respond with valid JSON only. Format: {\"reasoning\":\"...\",\"tool\":\"...\",\"arguments\":{...}}"
    try:
        reply = ask_puter([
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message}
        ])
        return parse_tool_json(reply)
    except:
        return {"tool": "reply_text", "arguments": {"text": "Sorry, error processing."}}

def parse_tool_json(text):
    """Extract JSON from AI response."""
    try:
        return json.loads(text)
    except:
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return {"tool": "reply_text", "arguments": {"text": text[:200]}}

# ─────────────────────────────────────────────
# 4. TOOL FUNCTION CALLING
# ─────────────────────────────────────────────
async def execute_tool(tool_name, args, client, me, event):
    """Execute a tool based on AI decision."""
    tools = {
        "reply_text": lambda: event.reply(args.get("text", "")),
        "block_user": lambda: client(functions.contacts.BlockRequest(id=args.get("user_id"))),
        "send_to_boss": lambda: client.send_message(me.id, args.get("text", "")),
        "add_memory": lambda: add_fact(args.get("user_id"), args.get("fact", "")),
        "ignore": lambda: None,
        "warn_user": lambda: event.reply(args.get("warning", "Stop that.")),
        "update_profile": lambda: update_profile_field(args.get("user_id"), args.get("field"), args.get("value")),
    }
    func = tools.get(tool_name)
    if func:
        try:
            await func()
            return True
        except Exception as e:
            print(f"[Tool Error] {tool_name}: {e}")
            return False
    return False

def add_fact(user_id, fact):
    if not fact:
        return
    prof = get_profile(user_id)
    if fact not in prof.get("interests", []):
        prof.setdefault("interests", []).append(fact)
        save_ltm()

def update_profile_field(user_id, field, value):
    prof = get_profile(user_id)
    if field and value is not None:
        prof[field] = value
        save_ltm()

# ─────────────────────────────────────────────
# 5. REASONING ENGINE PROMPTS
# ─────────────────────────────────────────────
REASONING_PROMPT = """You are an autonomous AI agent managing a Telegram account.

CURRENT USER PROFILE:
{profile}

CONVERSATION HISTORY (STM):
{stm}

EMOTION: {emotion} ({emotion_conf})

RELATIONSHIP: {relation} (score: {rel_score})

AVAILABLE TOOLS:
1. reply_text: Reply to the message. Arguments: {"text": "your reply"}
2. block_user: Block this user. Arguments: {"user_id": id}
3. send_to_boss: Notify the account owner. Arguments: {"text": "message"}
4. add_memory: Remember a fact about this user. Arguments: {"user_id": id, "fact": "fact"}
5. warn_user: Warn the user. Arguments: {"warning": "message"}
6. ignore: Do nothing.

DYNAMIC INSTRUCTIONS:
{dyn_inst}

Think step-by-step then respond with JSON only:
{"reasoning":"...","tool":"tool_name","arguments":{...}}"""

REFLECTION_PROMPT = """You are an AI analyzing your own performance today.

TODAY'S STATS:
{stats}

RECENT EPISODIC EVENTS:
{episodic}

Analyze:
1. What mistakes did you make?
2. What should improve?
3. New operating instructions for tomorrow.

Respond in JSON:
{"mistakes":["..."],"improvements":["..."],"new_instructions":["..."]}"""

# ─────────────────────────────────────────────
# 6. SELF-REFLECTION ENGINE
# ─────────────────────────────────────────────
async def run_daily_reflection(client, me):
    """Run at 23:00 each day."""
    stats = {
        "positive_today": sum(p.get("positive_count", 0) for p in ltm_cache.values()),
        "negative_today": sum(p.get("negative_count", 0) for p in ltm_cache.values()),
        "total_users": len(ltm_cache),
        "episodic_count": len(episodic),
    }
    recent_ep = [e for e in episodic if now_ts() - e.get("ts", 0) < 86400][-10:]
    ep_text = "\n".join(f"- {e['event']}" for e in recent_ep)

    prompt = REFLECTION_PROMPT.format(stats=json.dumps(stats), episodic=ep_text)
    result = ask_agent(prompt, "Analyze today and generate improvements.")

    try:
        data = json.loads(result)
        new_insts = data.get("new_instructions", [])
        if new_insts:
            with open(dyn_inst_path, "w", encoding="utf-8") as f:
                f.write("\n".join(new_insts))
        await client.send_message(me.id, f"Reflection done. {len(new_insts)} new instructions added.")
    except:
        await client.send_message(me.id, f"Reflection completed.\nPositive: {stats['positive_today']}\nNegative: {stats['negative_today']}")

# ─────────────────────────────────────────────
# 7. KNOWLEDGE EXTRACTION
# ─────────────────────────────────────────────
KNOWLEDGE_EXTRACT_PROMPT = """Extract any factual knowledge about the user from this message.
If the user mentions their job, skills, interests, or personal info - extract it.
If no information, return empty.

Message: {text}

JSON:
{"has_info": true/false, "facts": ["fact1", "fact2"], "confidence": 0.95}"""

async def extract_knowledge(user_id, text):
    if len(text) < 10:
        return
    try:
        reply = ask_puter([
            {"role": "system", "content": KNOWLEDGE_EXTRACT_PROMPT.format(text=text)},
            {"role": "user", "content": "Extract knowledge from the above message."}
        ])
        data = json.loads(reply)
        if data.get("has_info") and data.get("facts"):
            for fact in data["facts"]:
                add_fact(user_id, fact)
    except:
        pass

# ─────────────────────────────────────────────
# 8. MESSAGE HANDLER (CORE)
# ─────────────────────────────────────────────
async def handle_message(event, client, me):
    text = (event.text or "").strip()
    if not text:
        return

    sender = await event.get_sender()
    sender_name = sender.first_name or "Unknown"
    user_id = event.sender_id
    is_self = isinstance(event.peer_id, PeerUser) and user_id == me.id

    # Self-chat → boss mode
    if is_self and event.out:
        await handle_boss(text, event, client, me)
        return

    if event.out:
        return

    # Ignore non-user chats for now (groups handled separately)
    if not isinstance(event.peer_id, PeerUser):
        return

    print(f"\n[DM {sender_name}]: {text}")

    # Update STM
    add_stm(user_id, "user", text)

    # Detect emotion
    emotion, emotion_conf = detect_emotion(text)
    prof = get_profile(user_id)
    prof["emotion_history"].append({"emotion": emotion, "ts": now_ts()})
    save_ltm()

    # Relationship scoring
    if emotion == "angry":
        update_relationship(user_id, -3, "angry message")
    elif emotion == "happy":
        update_relationship(user_id, 1, "positive message")

    # Knowledge extraction (async)
    asyncio.create_task(extract_knowledge(user_id, text))

    # Build reasoning prompt
    profile_json = json.dumps(prof, indent=2)
    stm_context = get_stm_context(user_id, 10)
    rel_score = prof["relationship_score"]
    relation = get_relationship_label(rel_score)

    with open(dyn_inst_path, "r", encoding="utf-8") as f:
        dyn_inst = f.read().strip() or "None."

    prompt = REASONING_PROMPT.format(
        profile=profile_json,
        stm=stm_context,
        emotion=emotion.upper(),
        emotion_conf=emotion_conf,
        relation=relation,
        rel_score=rel_score,
        dyn_inst=dyn_inst
    )

    # AI decides
    decision = ask_with_tools(prompt, f"[{sender_name}]: {text}")

    tool = decision.get("tool", "reply_text")
    args = decision.get("arguments", {})
    reasoning = decision.get("reasoning", "")

    print(f"  [Reasoning]: {reasoning}")
    print(f"  [Tool]: {tool}")

    if tool == "reply_text":
        reply = args.get("text", "")
        if reply and not (len(reply) < 2 and reply.strip() in {'.', ',', '!', '?'}):
            add_stm(user_id, "assistant", reply)
            await event.reply(reply)
            print(f"  [Bot]: {reply}")
        return

    await execute_tool(tool, args, client, me, event)

async def handle_boss(text, event, client, me):
    """Handle messages from Saved Messages (boss chat)."""
    print(f"\n[Boss]: {text}")
    add_stm(me.id, "boss", text)

    tracked_name = "Unknown"
    context = get_stm_context(me.id, 15)

    prompt = f"""You are the personal AI secretary. Your boss is talking to you.

Recent conversation:
{context}

Your boss said: "{text}"

You can:
- Report about tracked users
- Answer questions
- Execute commands (block, send message, etc.)
- Give suggestions

Be direct, helpful. Use same language as your boss."""
    try:
        reply = ask_agent(prompt, text)
        add_stm(me.id, "secretary", reply)
        await event.reply(reply)
        print(f"  [Secretary]: {reply}")
    except Exception as e:
        print(f"  [Boss Error]: {e}")

# ─────────────────────────────────────────────
# 9. MAIN
# ─────────────────────────────────────────────
async def main():
    client = TelegramClient("session", API_ID, API_HASH)
    await client.start(phone=config["phone"])
    me = await client.get_me()
    print(f"\n=== AGENT V3 ===")
    print(f"Logged in: {me.first_name} (@{me.username})")
    print(f"Model: {AI_MODEL}")
    print(f"Memory: {MEMORY_DIR}/")
    print(f"Users in LTM: {len(ltm_cache)}")
    print(f"Episodic events: {len(episodic)}")

    # Periodic self-reflection (daily at 23:00)
    async def reflection_loop():
        while True:
            await asyncio.sleep(3600)
            h = datetime.now().hour
            if h == 23:
                await run_daily_reflection(client, me)
                await asyncio.sleep(7200)

    asyncio.create_task(reflection_loop())

    @client.on(events.NewMessage)
    async def handler(event):
        await handle_message(event, client, me)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
