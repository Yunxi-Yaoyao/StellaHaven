"""Create the isolated CI database using the already installed driver."""
import os
import psycopg2
from psycopg2 import sql

name = os.environ["POSTGRES_DB"] + "_test"
if name != "stella_test":
    raise SystemExit("CI database must be stella_test")
connection = psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
    user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
    dbname=os.environ["POSTGRES_DB"], connect_timeout=10)
connection.autocommit = True
try:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,))
        if not cursor.fetchone():
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    print("CI test database ready:", name)
finally:
    connection.close()
