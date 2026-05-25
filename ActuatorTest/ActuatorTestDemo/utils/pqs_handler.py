import psycopg2
import psycopg2.extras
import datetime
import json
import os
import dotenv
from psycopg2 import pool
from collections import defaultdict

dotenv.load_dotenv(dotenv_path= os.path.join(os.path.dirname(__file__), '../secrets/.env'))

# postgresql_connection = psycopg2.connect(host = os.getenv("POSTGRESQL_HOST"), 
#                             port = os.getenv("POSTGRESQL_PORT"), database = os.getenv("POSTGRESQL_DB"), 
#                             user = os.getenv("POSTGRESQL_USER"), password = os.getenv("POSTGRESQL_PASSWORD"))

# session_maker = psycopg2.extras.RealDictCursor(postgresql_connection)

# cursor = postgresql_connection.cursor()
postgresql_connection_pool = pool.SimpleConnectionPool(1, 5, host = os.getenv("POSTGRESQL_HOST"),
                            port = os.getenv("POSTGRESQL_PORT"), database = os.getenv("POSTGRESQL_DB"),
                            user = os.getenv("POSTGRESQL_USER"), password = os.getenv("POSTGRESQL_PASSWORD"))


def pivot_and_insert_telemetry(raw_batch, device_id):
    """
    Takes a raw batch of narrow CAN messages, pivots them into JSONB 
    time buckets, and bulk inserts them into the Hypertable.
    """
    # --- STEP A: Pivot to JSONB ---
    grouped_data = defaultdict(dict)
    
    for msg in raw_batch:
        # Truncate timestamp to the nearest second (e.g., "2023-10-27T10:00:00")
        # Use msg["timestamp"][:21] if you want 100ms precision instead
        time_bucket = msg["timestamp"][:19] 
        var_name = msg["variable_name"].lower()
        
        # Group variables occurring at the same time into a single dictionary
        grouped_data[time_bucket][var_name] = msg["data"]

    # Flatten back into a list of dictionaries for psycopg2
    wide_rows = []
    for time_bucket, payload_dict in grouped_data.items():
        wide_rows.append({
            "timestamp": time_bucket,
            "device_id": device_id,
            "payload": json.dumps(payload_dict) # Serialize dict to JSON string
        })

    # --- STEP B: Bulk Insert ---
    insert_query = """
        INSERT INTO actuator_test_db_runin (timestamp, device_id, payload) 
        VALUES %s
    """
    template = "(%(timestamp)s, %(device_id)s, %(payload)s::jsonb)"

    # Borrow a connection from the pool
    conn = db_pool.getconn()
    
    try:
        with conn.cursor() as cursor:
            # execute_values is heavily optimized for array insertion
            psycopg2.extras.execute_values(
                cursor, 
                insert_query, 
                wide_rows, 
                template=template, 
                page_size=1500
            )
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        print(f"Insert failed: {e}")
        # Depending on your requirements, you might log this to a file
        # or raise the exception to stop the test.
        
    finally:
        # ALWAYS return the connection to the pool
        db_pool.putconn(conn)


def upload_test_record(record_list, device_id_cache, max_retries=3):
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