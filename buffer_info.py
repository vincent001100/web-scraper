"""Read-only: what can a Buffer key see? Lists channels, and asks Buffer's API to describe the post
settings for Pinterest (board, title, link). Creates, edits and deletes nothing.
Run from Actions: Buffer info (choose pet-shelf or solvix)."""
import json, os, sys
from buffer_post import Buffer, BufferError, say, write_summary

TYPE_Q = """query($n: String!) { __type(name: $n) { name kind inputFields { name type { name kind ofType { name kind ofType { name kind } } } }
  fields { name type { name kind ofType { name kind ofType { name kind } } } } enumValues { name } } }"""

def describe(b, name):
    try:
        t = b.ask(TYPE_Q, {"n": name}).get("__type")
    except BufferError as e:
        return f"{name}: could not describe ({e})"
    if not t: return f"{name}: (no such type)"
    def ty(x):
        while x and not x.get("name"): x = x.get("ofType")
        return (x or {}).get("name")
    parts = [f"{f['name']}: {ty(f['type'])}" for f in (t.get("inputFields") or t.get("fields") or [])]
    parts += [e["name"] for e in (t.get("enumValues") or [])]
    return f"{name} ({t['kind']}): " + ", ".join(parts)

def main():
    which = (os.environ.get("WHICH") or "pet-shelf").strip()
    key = os.environ.get("PET_SHELF_BUFFER_API_KEY" if which == "pet-shelf" else "BUFFER_API_KEY")
    b = Buffer(key)
    lines = [f"Buffer account: {which}", "Channels:"]
    for c in b.channels():
        lines.append(f"  - {c['service']:<10} '{c['name']}'  id {c['id']}")
    try:   # every channel with its locked/disconnected state, and Pinterest boards
        orgs = (b.ask("query { account { organizations { id name } } }").get("account") or {}).get("organizations") or []
        for o in orgs:
            lines.append(f"Organization '{o.get('name')}' ({o.get('id')}):")
            q = ("query { channels(input: { organizationId: " + json.dumps(o["id"]) + " }) { id name service "
                 "isLocked isDisconnected metadata { ... on PinterestMetadata { boards { serviceId name } } } } }")
            for c in b.ask(q).get("channels") or []:
                lines.append(f"  - {c.get('service')} '{c.get('name')}' locked={c.get('isLocked')} "
                             f"disconnected={c.get('isDisconnected')}")
                for bd in ((c.get("metadata") or {}).get("boards") or []):
                    lines.append(f"      board '{bd.get('name')}' serviceId {bd.get('serviceId')}")
    except (BufferError, KeyError, TypeError) as e:
        lines.append(f"(channel details not available: {e})")
    for n in ("CreatePostInput", "PostInputMetaData", "PinterestPostMetaDataInput", "PinterestMetaDataInput", "PinterestPostInput", "Channel", "Service"):
        lines.append(describe(b, n))
    # find every input type whose name mentions Pinterest
    try:
        types = b.ask("query { __schema { types { name } } }")["__schema"]["types"]
        pins = [t["name"] for t in types if "interest" in t["name"].lower() or "board" in t["name"].lower()]
        lines.append("Types about Pinterest/boards: " + ", ".join(pins))
        for n in pins[:8]: lines.append(describe(b, n))
    except (BufferError, KeyError, TypeError) as e:
        lines.append(f"(schema list not available: {e})")
    text = "\n".join(lines); say(text); write_summary("### Buffer info\n```\n" + text + "\n```")
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except BufferError as e:
        print(f"::error::{e}"); sys.exit(1)
