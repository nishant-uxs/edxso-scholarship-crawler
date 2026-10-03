import sqlite3

c = sqlite3.connect("data/scholarships.db")
for q in ("%Reliance%", "%MEHERBAI%", "%Means%"):
    print(q, c.execute("select id, name from scholarships where name like ?", (q,)).fetchall())
