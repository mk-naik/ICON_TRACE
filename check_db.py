import sqlite3

db_path = 'icontrace.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT build_instance, COUNT(*) FROM serial GROUP BY build_instance")
print("Serial build_instance counts:")
for row in cur.fetchall():
    print(row)

cur.execute("""
    SELECT f.serial, s.model, s.build_instance 
    FROM fqc_record f
    LEFT JOIN serial s ON s.serial = f.serial
    LIMIT 10
""")
print("\nRecent FQC records and their joined serial build_instances:")
for row in cur.fetchall():
    print(row)

conn.close()
