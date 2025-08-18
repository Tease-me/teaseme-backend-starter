import redis

r = redis.Redis(host='localhost', port=6379, db=0)

for key in r.keys("message_store:*"):
    print(f"\n=== {key.decode()} ===")
    messages = r.lrange(key, 0, -1)
    for m in messages:
        txt = m.decode(errors="ignore")
        if "😊" in txt or "😉" in txt or "😄" in txt:  # filtra por emoji
            print("EMOJI FOUND:", txt)
        else:
            print(txt)