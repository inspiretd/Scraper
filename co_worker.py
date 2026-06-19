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
TRACK_USERNAME = "@wIw11111"

# ─── JSON helpers ───
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

# ─── MEMORY SYSTEM ───
stm = defaultdict(lambda: {"messages": [], "last_seen": 0})
ltm_path = os.path.join(MEMORY_DIR, "user_profiles.json")
ltm_cache = read_json(ltm_path, {})
user_styles_path = os.path.join(MEMORY_DIR, "user_styles.json")
user_styles = read_json(user_styles_path, {})  # user_id -> [style_samples]
contacts_path = os.path.join(MEMORY_DIR, "contacts.json")
contacts = read_json(contacts_path, {})  # user_id -> {name, username, bio, location, job, notes, known_from}
episodic_path = os.path.join(MEMORY_DIR, "episodic_memory.json")
episodic = read_json(episodic_path, [])
semantic_path = os.path.join(MEMORY_DIR, "semantic_memory.json")
semantic = read_json(semantic_path, {"best_style": "adaptive", "avoid_topics": [], "trust_default": 50})
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

def save_user_styles():
    write_json(user_styles_path, user_styles)

def save_contacts():
    write_json(contacts_path, contacts)

def get_profile(user_id):
    uid = str(user_id)
    if uid not in ltm_cache:
        ltm_cache[uid] = {
            "language": "unknown", "interests": [], "style": "unknown",
            "relationship_score": 50, "interaction_count": 0, "last_seen": 0,
            "positive_count": 0, "negative_count": 0, "emotion_history": []
        }
    return ltm_cache[uid]

def update_relationship(user_id, delta, reason=""):
    prof = get_profile(user_id)
    prof["relationship_score"] = max(0, min(100, prof["relationship_score"] + delta))
    prof["interaction_count"] += 1
    if delta > 0: prof["positive_count"] += 1
    elif delta < 0: prof["negative_count"] += 1
    prof["last_seen"] = now_ts()
    save_ltm()
    if abs(delta) >= 10:
        add_episodic(user_id, f"Relationship change: {delta} ({reason})", abs(delta))

def add_episodic(user_id, event, importance=5):
    episodic.append({
        "ts": now_ts(), "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "user_id": user_id, "event": event, "importance": min(importance, 10)
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

def add_fact(user_id, fact):
    if not fact: return
    prof = get_profile(user_id)
    if fact not in prof.get("interests", []):
        prof.setdefault("interests", []).append(fact)
        save_ltm()

# ─── TEXT FILTER (from auto_reply) ───
def is_meaningless(text):
    cleaned = re.sub(r'[\s\U0001F600-\U0010FFFF]', '', text)
    if not cleaned: return True
    letters = [c for c in cleaned if c.isalpha()]
    if not letters: return True
    vowels = set('аеёиоуыэюяaeiou')
    vowel_count = sum(1 for c in letters if c.lower() in vowels)
    if vowel_count / len(letters) < 0.1: return True
    cons_max = 0; cur = 0
    for c in letters:
        if c.lower() not in vowels: cur += 1; cons_max = max(cons_max, cur)
        else: cur = 0
    if cons_max >= 5: return True
    rows = [set('qwertyuiop'), set('asdfghjkl'), set('zxcvbnm'), set('йцукенгшщзхъ'), set('фывапролджэ'), set('ячсмитьбю')]
    for row in rows:
        row_letters = [c.lower() for c in letters if c.lower() in row]
        if len(row_letters) >= 3 and len(row_letters) / len(letters) > 0.8: return True
    return False

# ─── EMOTION DETECTION ───
def detect_emotion(text):
    angry = {'idiot','fuck','bastard','tupoy','ebal','huinya','dolboyob','pidor','xuy','blya','nahuy','musor','tentak','ahmoq','sikim','qanjiq','jalyab','баран','лох','тупой','ебан','хуй','бля','нах','пидор'}
    happy = {'haha','lol','хаха','круто','супер','rahmat','yaxshi',"zo'r",'рад'}
    lower = text.lower()
    a = sum(1 for w in angry if w in lower)
    h = sum(1 for w in happy if w in lower)
    if a > h: return "angry", min(0.99, 0.6 + a * 0.1)
    if h > 0: return "happy", min(0.95, 0.5 + h * 0.1)
    return "neutral", 0.5

# ─── AI ───
def ask_puter(messages, model=AI_MODEL, timeout=120):
    payload = {
        "interface": "puter-chat-completion", "driver": "ai-chat",
        "method": "complete", "args": {"messages": messages, "model": model}, "test_mode": False
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {PUTER_TOKEN}"}
    r = requests.post(f"{PUTER_API}/drivers/call", json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    c = r.json()["result"]["message"]["content"]
    if isinstance(c, list): return " ".join(x.get("text","") for x in c if isinstance(x,dict))
    return c

def ask_agent(system_prompt, user_message):
    try: return ask_puter([{"role":"system","content":system_prompt},{"role":"user","content":user_message}])
    except Exception as e: return f"[ERROR: {e}]"

def ask_with_tools(system_prompt, user_message):
    prompt = system_prompt + "\n\nRespond with JSON only: {\"reasoning\":\"...\",\"tool\":\"...\",\"arguments\":{...}}"
    try:
        reply = ask_puter([{"role":"system","content":prompt},{"role":"user","content":user_message}])
        return parse_tool_json(reply)
    except: return {"tool":"reply_text","arguments":{"text":"Sorry, error."}}

def parse_tool_json(text):
    try: return json.loads(text)
    except:
        m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if m:
            try: return json.loads(m.group())
            except: pass
    return {"tool":"reply_text","arguments":{"text":text[:200]}}

# ─── TRACKING ───
tracked_user_obj = None
tracked_user_id = None
boss_online = True  # starts True, flips to False after 3min idle
boss_last_active = 0  # timestamp of last outgoing message
boss_sleeping = False  # boss told bot to sleep — no auto-replies
away_message = ""  # custom away message to reply with when sleeping
tracked_stats = {
    "online_count": 0, "offline_count": 0, "msg_count": 0,
    "groups_seen": set(), "last_online": None, "first_seen": datetime.now(),
    "last_profile_name": None, "last_profile_username": None, "event_buffer": []
}

async def resolve_tracked_user(client, me):
    global tracked_user_obj, tracked_user_id
    try:
        u = await client.get_entity(TRACK_USERNAME.lstrip("@"))
        tracked_user_obj = u; tracked_user_id = u.id
        n = u.first_name or TRACK_USERNAME
        await client.send_message(me.id, f"Boss, {n} ni kuzatish boshlanadi.")
        return True
    except: return False

async def check_gifts(client, me):
    if not tracked_user_id: return
    try:
        full = await client(GetFullUserRequest(id=tracked_user_id))
        for a in dir(full):
            if 'gift' in a.lower() or 'star' in a.lower():
                v = getattr(full, a)
                if v:
                    await client.send_message(me.id, f"Gift: {a} = {v}")
    except: pass

async def setup_tracking(client, me):
    global tracked_stats
    if not tracked_user_id: return
    n = tracked_user_obj.first_name or TRACK_USERNAME
    tracked_stats["last_profile_name"] = tracked_user_obj.first_name
    tracked_stats["last_profile_username"] = tracked_user_obj.username

    async def flush_report():
        if tracked_stats["event_buffer"]:
            ev = "\n".join(tracked_stats["event_buffer"][-5:])
            tracked_stats["event_buffer"].clear()
            p = f"Report about {n}:\n{ev}\n\nSummarize as a secretary."

    @client.on(events.UserUpdate)
    async def status_handler(event):
        if event.user_id == tracked_user_id:
            s = event.status
            if isinstance(s, UserStatusOnline):
                tracked_stats["online_count"] += 1
                tracked_stats["last_online"] = datetime.now()
                tracked_stats["event_buffer"].append(f"Online #{tracked_stats['online_count']}")
            elif isinstance(s, UserStatusOffline):
                tracked_stats["event_buffer"].append("Offline")

    @client.on(events.NewMessage)
    async def profile_check(event):
        if event.sender_id == tracked_user_id:
            tracked_stats["msg_count"] += 1
            try:
                u = await event.get_sender()
                if u.first_name != tracked_stats["last_profile_name"]:
                    tracked_stats["event_buffer"].append(f"Name changed: {tracked_stats['last_profile_name']} -> {u.first_name}")
                    tracked_stats["last_profile_name"] = u.first_name
            except: pass

    await check_gifts(client, me)
    asyncio.create_task(gift_loop(client, me))

    async def daily():
        while True:
            await asyncio.sleep(3600)
            if datetime.now().hour == 23:
                await client.send_message(me.id,
                    f"Daily for {n}: online {tracked_stats['online_count']}x, "
                    f"msgs {tracked_stats['msg_count']}, groups {len(tracked_stats['groups_seen'])}")
    asyncio.create_task(daily())

async def gift_loop(client, me):
    await asyncio.sleep(300)
    while True:
        await check_gifts(client, me)
        await asyncio.sleep(3600)

# ─── STYLE & CONTACT LEARNING ───
async def learn_boss_style(client):
    """Scan all recent outgoing messages to learn how the boss writes."""
    samples = []
    async for m in client.iter_messages(None, limit=200):
        if m.out and m.text and len(m.text) > 8 and not m.text.startswith("http"):
            samples.append(m.text.strip())
        if len(samples) >= 15:
            break
    if samples:
        user_styles["_boss_style"] = samples
        save_user_styles()
        print(f"  Boss style: {len(samples)} samples collected")

async def update_contact_info(client, user_id, sender):
    """Store/update contact details from Telegram profile."""
    uid = str(user_id)
    if uid not in contacts or contacts[uid].get("name") != sender.first_name:
        contacts[uid] = {
            "name": sender.first_name or "",
            "username": sender.username or "",
            "phone": "",
            "bio": "", "location": "", "job": "",
            "notes": "", "known_from": datetime.now().isoformat()
        }
        try:
            full = await client(GetFullUserRequest(id=user_id))
            if hasattr(full, 'full_user') and hasattr(full.full_user, 'about'):
                contacts[uid]["bio"] = full.full_user.about or ""
        except: pass
        save_contacts()
    return contacts[uid]

def get_contact_summary(user_ids):
    """Return a readable summary of contacts for boss."""
    lines = []
    for uid in user_ids:
        uid = str(uid)
        if uid in contacts:
            c = contacts[uid]
            parts = [c.get("name","?")]
            if c.get("username"): parts.append(f"@{c['username']}")
            note = c.get("notes", "")
            if note: parts.append(f"({note[:80]})")
            if c.get("bio"): parts.append(f"— {c['bio'][:60]}")
            if c.get("location"): parts.append(c['location'])
            if c.get("job"): parts.append(c['job'])
            lines.append(" | ".join(parts))
    return "\n".join(lines) if lines else "0 known contacts"

# ─── TOOLS ───
async def execute_tool(tool_name, args, client, me, event, text):
    tools = {
        "reply_text": lambda: event.reply(args.get("text","")) if args.get("text") else None,
        "block_user": lambda: client(functions.contacts.BlockRequest(id=args.get("user_id"))),
        "send_to_boss": lambda: client.send_message(me.id, args.get("text","")),
        "add_memory": lambda: add_fact(args.get("user_id"), args.get("fact","")),
        "ignore": lambda: None,
        "warn_user": lambda: event.reply(args.get("warning","Stop.")),
    }
    f = tools.get(tool_name)
    if f:
        try:
            await f()
            return True
        except: pass
    return False

# ─── GROUPS (from auto_reply) ───
async def handle_group_message(event, client, me, text, chat):
    sender = await event.get_sender()
    sender_name = sender.first_name or "Unknown"
    chat_id = event.chat_id

    is_mentioned = False
    if event.mentioned or (event.message and event.message.entities):
        for e in event.message.entities or []:
            if isinstance(e, MessageEntityMentionName) and e.user_id == me.id: is_mentioned = True
            elif hasattr(e,'offset') and hasattr(e,'length'):
                if me.username and text[e.offset:e.offset+e.length].lower() == f"@{me.username.lower()}": is_mentioned = True
    is_reply_to_me = False
    if event.message and event.message.reply_to:
        try:
            r = await event.message.get_reply_message()
            if r and r.sender_id == me.id: is_reply_to_me = True
        except: pass

    if not is_mentioned and not is_reply_to_me:
        if tracked_user_id and sender.id == tracked_user_id:
            tracked_stats["groups_seen"].add(chat.title or "?")
            tracked_stats["event_buffer"].append(f"[{chat.title}]: {text[:100]}")
        return

    ctx = []
    async for m in client.iter_messages(chat_id, limit=10):
        if m.text:
            try:
                s = await m.get_sender(); n = s.first_name if s else "?"
                ctx.insert(0, f"[{n}]: {m.text}")
            except: ctx.insert(0, f"[?]: {m.text}")

    p = f"Group: {chat.title}\nContext:\n" + "\n".join(ctx[-8:]) + f"\n\n{sender_name} addressed you: \"{text}\"\nReply naturally in their language."
    try:
        r = ask_agent("You are a normal person in a group chat. Reply naturally, matching the chat's language and tone.", p)
        if r and not (len(r)<3): await event.reply(r)
    except: pass

# ─── DM HANDLER ───
async def handle_dm(event, client, me, text):
    sender = await event.get_sender()
    sender_name = sender.first_name or "Unknown"
    user_id = event.sender_id

    if is_meaningless(text):
        print(f"[{sender_name}]: filtered")
        return
    print(f"[DM {sender_name}]: {text}")

    add_stm(user_id, "user", text)
    emotion, emotion_conf = detect_emotion(text)

    prof = get_profile(user_id)
    if emotion == "angry": update_relationship(user_id, -3, "anger")
    elif emotion == "happy": update_relationship(user_id, 1, "positive")

    # Block command
    if any(kw in text.lower() for kw in ['block','blok','блок']):
        await client(functions.contacts.BlockRequest(id=user_id))
        print(f"[Blocked] {sender_name}")
        add_episodic(user_id, "Blocked user", 7)
        return

    # Learn contact info
    ci = await update_contact_info(client, user_id, sender)

    pj = json.dumps(prof, indent=2)
    sc = get_stm_context(user_id, 10)
    rs = prof["relationship_score"]
    rl = get_relationship_label(rs)

    with open(dyn_inst_path, "r", encoding="utf-8") as f:
        di = f.read().strip() or "None."

    style_samples = user_styles.get("_boss_style", [])
    style_hint = ""
    if style_samples:
        style_hint = f"The account owner's writing style (reply like this):\n" + "\n".join("> "+s for s in style_samples[:3])

    system_p = f"""You are an AI secretary managing a Telegram account.

User profile: {pj}
Contact: {json.dumps(ci, indent=2)}
History: {sc}
Emotion: {emotion.upper()} ({emotion_conf})
Relationship: {rl} ({rs})

{style_hint}
Instructions: {di}

Tools: reply_text, block_user, send_to_boss, add_memory, warn_user, ignore

Reply JSON: {{"reasoning":"...","tool":"reply_text","arguments":{{"text":"..."}}}}"""

    decision = ask_with_tools(system_p, f"[{sender_name}]: {text}")
    tool = decision.get("tool", "reply_text")
    args = decision.get("arguments", {})

    # Knowledge extraction
    asyncio.create_task(extract_knowledge_async(user_id, text))

    if tool == "reply_text" and args.get("text"):
        reply = args["text"]
        if len(reply) < 2 and reply.strip() in {'.',',','!','?','...'}:
            return
        add_stm(user_id, "assistant", reply)
        try: await event.reply(reply)
        except: pass
        print(f"  [Bot]: {reply}")
        return

    await execute_tool(tool, args, client, me, event, text)

# ─── BOSS CHAT ───
def extract_name_from_question(text):
    """Extract person name from questions like 'X kim?', 'who is X?', 'X кто такой?' etc."""
    t = text.strip().lower()
    # Patterns: "X kim?", "X кто?", "X qayerdan?", "who is X?", "кто такой X?"
    patterns = [
        (r'^(.+?)\s+kim\??$', 1),          # "Dinara kim?"
        (r'^(.+?)\s+кто\??$', 1),           # "Динара кто?"
        (r'^(.+?)\s+кто\s+такой\??$', 1),   # "Динара кто такой?"
        (r'^(.+?)\s+who\??$', 1),           # "Dinara who?"
        (r'^who\s+is\s+(.+?)\??$', 1),       # "who is Dinara?"
        (r'^кто\s+такой\s+(.+?)\??$', 1),    # "кто такой Dinara?"
        (r'^кто\s+(.+?)\??$', 1),            # "кто Dinara?"
        (r'^(.+?)\s+qayerdan\??$', 1),       # "Dinara qayerdan?"
        (r'^(.+?)\s+откуда\??$', 1),         # "Dinara откуда?"
        (r'^(.+?)\s+nima\??$', 1),           # "Dinara nima?"
        (r'^(.+?)\s+что\??$', 1),            # "Dinara что?"
    ]
    for pat, grp in patterns:
        m = re.match(pat, t)
        if m:
            name = m.group(1).strip().title()
            # Filter out pure question words
            if name.lower() in ("kim", "who", "кто", "qayerdan", "откуда", "nima", "что", "nechi", "сколько", "qanaqa", "как", "kani", "где", "qaerda", "qachon", "когда"):
                return None
            return name
    return None

async def search_person_in_chats(client, name_query):
    """Search all chats for messages with a person (by name in dialog or message text)."""
    name_lower = name_query.lower().strip()
    results = []
    seen = set()
    try:
        dialogs = await client.get_dialogs(limit=100)
        # First pass: find the exact DM chat
        for d in dialogs:
            if not d.entity: continue
            if d.name and name_lower == d.name.lower() or (d.name and name_lower in d.name.lower()):
                results.append(f"📁 DM with {d.name}:")
                async for m in client.iter_messages(d.entity, limit=30):
                    if m.text:
                        s = await m.get_sender(); sn = s.first_name if s else "?"
                        line = f"  [{sn}]: {m.text[:200]}"
                        if line not in seen:
                            seen.add(line); results.append(line)
                break
        # Second pass: search mentions in all group chats
        for d in dialogs:
            if not d.entity: continue
            if isinstance(d.entity, (PeerChat, PeerChannel)):
                async for m in client.iter_messages(d.entity, limit=30):
                    if m.text and name_lower in m.text.lower():
                        s = await m.get_sender(); sn = s.first_name if s else "?"
                        line = f"[{d.name}] {sn}: {m.text[:200]}"
                        if line not in seen:
                            seen.add(line); results.append(line)
                            if len(results) >= 25: break
            if len(results) >= 25: break
    except Exception as e:
        results.append(f"[search error: {e}]")
    return results[:25]

async def handle_boss(text, event, client, me):
    add_stm(me.id, "boss", text)
    n = tracked_user_obj.first_name if tracked_user_obj else "?"
    ctx = get_stm_context(me.id, 10)
    stats = f"Online: {tracked_stats['online_count']} | Msgs: {tracked_stats['msg_count']} | Groups: {len(tracked_stats['groups_seen'])}"

    # Build contact summary
    all_contacts = get_contact_summary(contacts.keys())
    # Build known facts from LTM
    facts = []
    for uid, p in list(ltm_cache.items())[:20]:
        nm = contacts.get(uid, {}).get("name", uid)
        ints = p.get("interests", [])
        if ints:
            facts.append(f"{nm}: {', '.join(ints[:5])}")
    kv = "\n".join(facts) if facts else "none yet"

    style_samples = user_styles.get("_boss_style", [])
    style_hint = ""
    if style_samples:
        style_hint = "Your boss writes like this (match this style):\n" + "\n".join("> "+s[:100] for s in style_samples[:5])

    # Check if boss is asking about a person — search chats if needed
    additional_context = ""
    try:
        person_name = extract_name_from_question(text)
        if person_name:
            print(f"[Search] Looking for '{person_name}' in chats...")
            await event.reply(f"🔍 '{person_name}' ni qidiryapman...")
            found = await search_person_in_chats(client, person_name)
            if found:
                chat_info = "\n".join(found[:15])
                additional_context = f"\n\nSearch results for '{person_name}':\n{chat_info}"
                contacts[f"_search_{person_name}"] = {"name": person_name, "notes": chat_info[:200], "known_from": datetime.now().isoformat()}
                save_contacts()
    except Exception as e:
        print(f"[Search error]: {e}")

    # ─── SLEEP / AWAY HANDLER ───
    global boss_sleeping, away_message
    t_lower = text.lower()
    # Wake up
    if boss_sleeping and any(w in t_lower for w in ["uyg'on", "uygon", "wake", "turiq", "туриқ", "проснись"]):
        boss_sleeping = False; away_message = ""
        await event.reply("✅ Uyg'ondim. Auto-reply yoqildi.")
        print("[Sleep] Woke up")
        return
    # Sleep command
    if any(w in t_lower for w in ["uxla", "sleep", "hech kimga"]):
        boss_sleeping = True
        # Check if away message provided
        parts = text.split("de.") if "de." in text else text.split("де.")
        if len(parts) > 1:
            away_message = parts[1].replace("de.", "").replace("де.", "").strip()
            if len(away_message) < 3:
                away_message = parts[0].strip()
        else:
            away_message = ""
        if away_message:
            await event.reply(f"✅ Tushundim. Hammaga: \"{away_message}\" deyman.")
        else:
            await event.reply("✅ Uxlap qoldim. Hech kimga javob bermayman.")
        print(f"[Sleep] Away msg: {away_message or 'none'}")
        return

    # ─── INSTRUCTION HANDLER ───
    try:
        instr_check = await asyncio.to_thread(ask_puter, [
            {"role":"system","content":"Is the user giving a COMMAND/INSTRUCTION about how you should behave? Examples: 'sen endi yomon gapirmaysan', 'bu odamga faqat yaxshi gapir', 'do not swear', 'be nice to X', 'ignore X', 'always reply in Uzbek'. If YES: return just the instruction text. If NO: return 'NONE'."},
            {"role":"user","content":text}
        ])
        instr = instr_check.strip().strip('"\'')
        if instr and instr != "NONE" and len(instr) > 3:
            with open(dyn_inst_path, "r", encoding="utf-8") as f:
                existing = f.read().strip()
            new_inst = f"[BOSS] {instr}"
            all_insts = [l for l in existing.split("\n") if l.strip()]
            all_insts.append(new_inst)
            with open(dyn_inst_path, "w", encoding="utf-8") as f:
                f.write("\n".join(all_insts[-20:]))
            await event.reply(f"✅ Tushundim: \"{instr}\"")
            print(f"[Instruction saved]: {instr}")
            return
    except: pass

    boss_nik = me.first_name or "Boss"
    p = f"""You are the secretary. {boss_nik} is talking to you.

Recent: {ctx}
Tracked user ({n}): {stats}

Known contacts:
{all_contacts}

Known facts:
{kv}

{additional_context}

{style_hint}

Address {boss_nik} by name ({boss_nik}). Never say 'Boss' or 'Бошлиқ'.
Answer from what you know. If unsure, search and say so.
Reply helpfully in {boss_nik}'s language. Be direct."""
    r = ask_agent(p, text)
    add_stm(me.id, "secretary", r)
    try: await event.reply(r)
    except: pass
    print(f"[Secretary]: {r[:80]}")

# ─── KNOWLEDGE EXTRACTION ───
async def extract_knowledge_async(user_id, text):
    if len(text) < 10: return
    try:
        r = ask_puter([{"role":"system","content":f"Extract facts from this message. JSON: {{\"facts\":[...], \"has_info\":bool}}\n\nMessage: {text}"},{"role":"user","content":"Extract."}])
        d = json.loads(r)
        if d.get("has_info"):
            for f in d.get("facts",[]):
                add_fact(user_id, f)
    except: pass

# ─── SELF-REFLECTION ───
async def run_reflection(client, me):
    global boss_sleeping
    stats = {
        "users": len(ltm_cache), "positive": sum(p.get("positive_count",0) for p in ltm_cache.values()),
        "negative": sum(p.get("negative_count",0) for p in ltm_cache.values()),
        "contacts": len(contacts), "episodic_events": len(episodic)
    }
    # Sample recent STM for learning
    recent_convos = {}
    for uid, data in list(stm.items())[:10]:
        msgs = [m["text"][:100] for m in data["messages"][-6:]]
        if msgs:
            recent_convos[str(uid)] = msgs
    context = json.dumps({"stats": stats, "recent": recent_convos}, ensure_ascii=False)
    p = f"Review today's work. Stats + conversation samples:\n{context}\n\nJSON: {{\"mistakes\":[],\"improvements\":[],\"new_instructions\":[],\"behavior_tweaks\":[]}}"
    r = ask_agent("You are a self-improving AI. Analyze what went wrong/right today and suggest concrete behavior changes.", p)
    try:
        d = json.loads(r)
        insts = d.get("new_instructions",[])
        tweaks = d.get("behavior_tweaks",[])
        all_updates = insts + [f"[SELF] {t}" for t in tweaks]
        if all_updates:
            with open(dyn_inst_path,"r",encoding="utf-8") as f:
                existing = f.read().strip()
            old_lines = [l for l in existing.split("\n") if l.strip()]
            combined = old_lines + all_updates
            with open(dyn_inst_path,"w",encoding="utf-8") as f:
                f.write("\n".join(combined[-30:]))
        # Log improvement
        log_path = os.path.join(MEMORY_DIR, "improvement_log.json")
        log = read_json(log_path, [])
        log.append({"date": datetime.now().isoformat(), "mistakes": d.get("mistakes",[]), "improvements": d.get("improvements",[])})
        write_json(log_path, log[-50:])
        await client.send_message(me.id, f"🧠 Self-reflect: {len(all_updates)} new instructions. {len(d.get('mistakes',[]))} mistakes reviewed.")
    except Exception as e:
        print(f"[Reflection error]: {e}")

# ─── CHAT SCANNER ───
async def scan_all_contacts(client, me):
    """Scan all DM chats, learn everyone's name, bio, recent messages."""
    print("\n=== SCANNING ALL CONTACTS ===")
    dialogs = await client.get_dialogs(limit=100)
    print(f"Total dialogs: {len(dialogs)}")
    scanned = 0
    for d in dialogs:
        if not d.entity or not isinstance(d.entity, PeerUser): continue
        uid = d.entity.user_id
        if uid == me.id: continue
        try:
            s = await client.get_entity(uid)
            await update_contact_info(client, uid, s)
            # Read last messages and extract facts
            msgs = []
            async for m in client.iter_messages(uid, limit=15):
                if m.text:
                    msgs.append(m.text.strip())
            if msgs:
                txt = "\n".join(msgs[:10])
                if len(txt) > 50:
                    summary = ask_puter([
                        {"role":"system","content":"Extract who this person is from chat history. Return JSON: {\"who\":\"short description\",\"language\":\"uz/ru/en/kk/other\",\"topics\":[topic1, topic2],\"relation\":\"friend/family/colleague/other\"}"},
                        {"role":"user","content":f"Chat with {s.first_name or '?'}:\n{txt[:2000]}"}
                    ])
                    try:
                        data = json.loads(summary)
                        prof = get_profile(uid)
                        prof["language"] = data.get("language", "unknown")
                        for t in data.get("topics", []):
                            if t not in prof.get("interests", []):
                                prof.setdefault("interests", []).append(t)
                        contacts[str(uid)]["notes"] = data.get("who", "")
                        contacts[str(uid)]["from_scan"] = True
                        save_ltm(); save_contacts()
                    except: pass
            scanned += 1
            print(f"  [{scanned}] {s.first_name or '?'} — scanned")
        except: pass
    print(f"Scanned {scanned} contacts")
    return dialogs

# ─── MAIN ───
async def main():
    client = TelegramClient("session", API_ID, API_HASH)
    await client.start(phone=PHONE)
    me = await client.get_me()
    print(f"\n=== CO-WORKER: auto_reply + agent_v3 ===")
    print(f"Logged in: {me.first_name} (@{me.username})")
    print(f"Model: {AI_MODEL}")
    print(f"Memory: {MEMORY_DIR}/ ({len(ltm_cache)} users, {len(episodic)} events)")

    await scan_all_contacts(client, me)
    await learn_boss_style(client)
    if await resolve_tracked_user(client, me):
        await setup_tracking(client, me)

    # Daily reflection at 23:00
    async def reflection_loop():
        while True:
            await asyncio.sleep(3600)
            if datetime.now().hour == 23:
                await run_reflection(client, me)
                await asyncio.sleep(7200)
    asyncio.create_task(reflection_loop())

    # Init boss as online, will go offline after 3min idle
    global boss_last_active
    boss_last_active = now_ts()

    async def offline_checker():
        global boss_online, boss_last_active
        while True:
            await asyncio.sleep(60)
            if boss_online and (now_ts() - boss_last_active) > 180:
                boss_online = False
                print(f"[Status] {datetime.now():%H:%M} Boss offline — auto-reply enabled")

    @client.on(events.NewMessage)
    async def handler(event):
        global boss_online, boss_last_active, boss_sleeping, away_message
        text = (event.text or "").strip()
        if not text: return

        # Track outgoing messages (boss is active)
        if event.out:
            boss_online = True
            boss_last_active = now_ts()

        # Boss chat (Saved Messages)
        if isinstance(event.peer_id, PeerUser) and event.sender_id == me.id and event.out:
            await handle_boss(text, event, client, me)
            return

        if event.out: return

        # Group messages (reply always if mentioned, unless sleeping)
        if isinstance(event.peer_id, (PeerChat, PeerChannel)):
            if boss_sleeping:
                print(f"[Group skipped — boss sleeping]: {text[:40]}")
                return
            chat = await event.get_chat()
            await handle_group_message(event, client, me, text, chat)
            return

        # DM messages — skip if boss is online or sleeping
        if isinstance(event.peer_id, PeerUser):
            if boss_sleeping:
                s = await event.get_sender()
                sn = s.first_name if s else "?"
                if away_message:
                    try: await event.reply(away_message)
                    except: pass
                    print(f"[DM {sn} away-reply]: {away_message[:40]}")
                else:
                    print(f"[DM {sn} skipped — boss sleeping]: {text[:40]}")
                return
            if boss_online:
                s = await event.get_sender()
                sn = s.first_name if s else "?"
                print(f"[DM {sn} skipped — boss online]: {text[:40]}")
                return
            await handle_dm(event, client, me, text)
            return

    asyncio.create_task(offline_checker())
    print("\nBoth agents running. Bot is active.\n")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
