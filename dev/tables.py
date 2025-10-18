import os, sqlite3, textwrap, pathlib, sys

db = os.getenv("VALAR_DB", str(pathlib.Path.home() /
                               "ve2fet/valar_database/valar.db"))
conn = sqlite3.connect(db)
for name, sql in conn.execute("SELECT name, sql FROM sqlite_master "
                              "WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
    print(f"\n-- {name} --")
    print(textwrap.dedent(sql).strip(), end="\n")
conn.close()
