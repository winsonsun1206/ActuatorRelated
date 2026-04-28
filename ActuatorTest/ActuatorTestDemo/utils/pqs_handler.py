import psycopg2
import psycopg2.extras
import datetime
import json
import os
import dotenv
from psycopg2 import pool

dotenv.load_dotenv(dotenv_path= os.path.join(os.path.dirname(__file__), '../secrets/.env'))

# postgresql_connection = psycopg2.connect(host = os.getenv("POSTGRESQL_HOST"), 
#                             port = os.getenv("POSTGRESQL_PORT"), database = os.getenv("POSTGRESQL_DB"), 
#                             user = os.getenv("POSTGRESQL_USER"), password = os.getenv("POSTGRESQL_PASSWORD"))

# session_maker = psycopg2.extras.RealDictCursor(postgresql_connection)

# cursor = postgresql_connection.cursor()
postgresql_connection_pool = pool.SimpleConnectionPool(1, 5, host = os.getenv("POSTGRESQL_HOST"),
                            port = os.getenv("POSTGRESQL_PORT"), database = os.getenv("POSTGRESQL_DB"),
                            user = os.getenv("POSTGRESQL_USER"), password = os.getenv("POSTGRESQL_PASSWORD"))


def upload_test_record(record_list, max_retries=3):
    insert_query = f"""
    INSERT INTO {os.getenv("POSTGRESQL_DB")} (
        can_bus, 
        can_bus_id, 
        serial_number, 
        part_number, 
        variable_name, 
        data, 
        unit, 
        timestamp
    ) VALUES %s
"""
    template = """(
        %(can_bus)s, 
        %(can_bus_id)s, 
        %(serial_number)s, 
        %(part_number)s, 
        %(variable_name)s, 
        %(data)s, 
        %(unit)s, 
        %(timestamp)s
    )"""
    for attempt in range(max_retries):
        conn = postgresql_connection_pool.getconn()
        try:
            with conn.cursor() as cursor:
                 psycopg2.extras.execute_values(cursor, insert_query, record_list, template=template, page_size= len(record_list))
            conn.commit()
            postgresql_connection_pool.putconn(conn)
            return
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            print(f"Database connection error: {e}. Retrying ({attempt + 1}/{max_retries})...  ")
            postgresql_connection_pool.putconn(conn, close=True)
            if attempt == max_retries - 1:
                print("Max retries reached. Failed to upload records.")
                raise e
        except Exception as e:
            conn.rollback()
            print(f"An error occurred: {e}")
            postgresql_connection_pool.putconn(conn)
            raise e

        
        
def fetch_records_by_serial_number(serial_number):
    query = f"""
    SELECT * FROM {os.getenv("POSTGRESQL_DB")} 
    WHERE serial_number = %s
    ORDER BY timestamp DESC
    """
    conn = postgresql_connection_pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(query, (serial_number,))
            records = cursor.fetchall()
        postgresql_connection_pool.putconn(conn)
        return records
    except Exception as e:
        print(f"An error occurred while fetching records: {e}")
        postgresql_connection_pool.putconn(conn)
        raise e
    
    
if __name__ == "__main__":
    # Example usage
    print(fetch_records_by_serial_number("SN123456789"))