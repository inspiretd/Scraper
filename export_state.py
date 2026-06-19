"""Export current state for Render deployment:
1. Convert session.session → StringSession
2. Bundle agent_memory/ files

Usage:
  python export_state.py

Then paste the STRING_SESSION and MEMORY_BUNDLE into Render env vars.
"""
import json, base64, os, glob

MEMORY_DIR = "agent_memory"

def encode_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def export_session():
    session_file = "session.session"
    if os.path.exists(session_file):
        data = encode_file(session_file)
        print(f"\n📁 session.session — {len(data)} chars")
        return data
    print("\n⚠️  session.session not found")
    return ""

def export_memory():
    bundle = {}
    for fname in os.listdir(MEMORY_DIR):
        path = os.path.join(MEMORY_DIR, fname)
        if os.path.isfile(path):
            bundle[fname] = encode_file(path)
    print(f"📁 agent_memory/ — {len(bundle)} files")
    return bundle

def main():
    print("=== STATE EXPORT ===\n")
    session_b64 = export_session()
    memory = export_memory()
    full = {"session": session_b64, "memory": memory}
    encoded = base64.b64encode(json.dumps(full).encode()).decode()
    print(f"\n{'='*50}")
    print(f"Total: {len(encoded)} chars")
    print(f"\nCopy this into Render env var STATE_BUNDLE:\n")
    print(encoded)
    print(f"\n{'='*50}")

if __name__ == "__main__":
    main()
