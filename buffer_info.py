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
    key = os.environ.get({"pet-shelf": "PET_SHELF_BUFFER_API_KEY", "pinterest": "PINTEREST_BUFFER_API_KEY"}
                         .get(which, "BUFFER_API_KEY"))
    b = Buffer(key)
    lines = [f"Buffer account: {which}", "Channels:"]
    for c in b.channels():
        lines.append(f"  - {c['service']:<10} '{c['name']}'  id {c['id']}")
    try:   # every channel with its locked/disconnected state, and Pinterest boards
        orgs = (b.ask("query { account { organizations { id name } } }").get("account") or {}).get("organizations") or []
        for o in orgs:
            lines.append(f"Organization '{o.get('name')}' ({o.get('id')}):")
            q = ("query { channels(input: { organizationId: " + json.dumps(o["id"]) + " }) { id name service type "
                 "isLocked isDisconnected scopes serviceId createdAt updatedAt "
                 "metadata { ... on PinterestMetadata { boards { serviceId name } } } } }")
            for c in b.ask(q).get("channels") or []:
                lines.append(f"  - {c.get('service')} '{c.get('name')}' locked={c.get('isLocked')} "
                             f"disconnected={c.get('isDisconnected')}")
                lines.append(f"      type={c.get('type')} permissions={c.get('scopes')} "
                             f"connected={c.get('createdAt')} refreshed={c.get('updatedAt')}")
                for bd in ((c.get("metadata") or {}).get("boards") or []):
                    lines.append(f"      board '{bd.get('name')}' serviceId {bd.get('serviceId')}")
                if c.get("service") == "pinterest":   # show exactly what Buffer returns
                    try:
                        raw = b.ask("query { channels(input: { organizationId: " + json.dumps(o["id"]) + " }) { id service "
                                    "metadata { __typename ... on PinterestMetadata { boards { id serviceId name url } } } } }")
                        lines.append("      raw: " + json.dumps([x for x in raw.get("channels") or [] if x.get("id") == c.get("id")]))
                    except BufferError as e:
                        lines.append(f"      raw metadata not available: {e}")
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
    post_id = (os.environ.get("POST_ID") or "").strip()
    if post_id:   # read-only: everything Buffer holds for one post (used to debug a failed pin)
        lines.append(describe(b, "Post"))
        for fields in ("id status text dueAt sentAt externalLink channelId error { message } "
                       "metadata { __typename ... on PinterestPostMetadata { title url board { id serviceId name url } } }",
                       "id status dueAt channelId error { message }"):
            try:
                got = b.ask("query { post(input: { id: " + json.dumps(post_id) + " }) { __typename ... on Post { " + fields + " } } }")
                lines.append(f"Post {post_id}: " + json.dumps(got)); break
            except BufferError as e:
                lines.append(f"Post {post_id}: question refused ({e})")
    text = "\n".join(lines); say(text); write_summary("### Buffer info\n```\n" + text + "\n```")
    return 0

if __name__ == "__main__":
    try: sys.exit(main())
    except BufferError as e:
        print(f"::error::{e}"); sys.exit(1)
