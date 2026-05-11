import json
from collections import defaultdict
from datetime import datetime
import psycopg2
import psycopg2.extras
import os
import dotenv

dotenv.load_dotenv(dotenv_path= os.path.join(os.path.dirname(__file__), '../secrets/.env'))


def pivot_to_jsonb(raw_data_list):
    pivot_data = defaultdict(dict)
    for record in raw_data_list:
        can_bus_id = record['can_bus_id']
        var_name = record['variable_name']
        time_bucket = record['timestamp'][:19]
        device_id = record['device_id']
        key = (time_bucket, device_id)
        pivot_data[key][var_name] = record['data']
        
    wide_format_data = []
    for (time_bucket, device_id), payload in pivot_data.items():
        wide_format_data.append({
            'timestamp': time_bucket,
            'device_id': device_id,
            'payload': json.dumps(payload)
        })
        
    return wide_format_data

def insert_pivoted_data_to_db(pgs_conn, wide_format_data):
    table_name = os.getenv("POSTGRESQL_DB")
    insert_query = f"""
    INSERT INTO {table_name} (timestamp, device_id, payload)
    VALUES %s
    """
    template = "(%(timestamp)s, %(device_id)s, %(payload)s::jsonb)"
    ### this template will insert the payload as jsonb data type, 
    # which allows us to query the json data efficiently in postgresql. 
    # The payload is a json string that contains the variable names and their corresponding data values for each device 
    # at each timestamp.
    try:
        with pgs_conn.cursor() as cursor:
            psycopg2.extras.execute_values(cursor, insert_query, wide_format_data, template=template, page_size=len(wide_format_data))
        pgs_conn.commit()
        
        
    except Exception as e:
        pgs_conn.rollback()
        print(f"Error inserting pivoted data: {e}")
    