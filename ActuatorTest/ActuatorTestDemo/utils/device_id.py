import redis
import psycopg2
import dotenv
import os
from datetime import datetime, timedelta
#from pqs_handler import postgresql_connection_pool

    
dotenv.load_dotenv(dotenv_path= os.path.join(os.path.dirname(__file__), '../secrets/.env'))

redis_cache = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT")),
    db=int(os.getenv("REDIS_DB_DEVICE_ID_CACHE")), decode_responses=True
)

def get_device_id_from_cache(pgs_conn, serial_number, partnumber, can_msg_id,station_name=None,can_port=None):
    # fast check the redis cache and return the device id if found, otherwise query the postgresql database and update the cache
    cache_key = f"{serial_number}_{partnumber}_{station_name}_{can_port}"
    device_id = redis_cache.get(cache_key)
    if device_id is not None:
        return int(device_id)
    else:
        query = f"""
        INSERT INTO devices (serial_number, part_number, station_name, can_port, can_msg_id)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (serial_number) DO UPDATE SET part_number = EXCLUDED.part_number, station_name = EXCLUDED.station_name, can_port = EXCLUDED.can_port, can_msg_id = EXCLUDED.can_msg_id
        RETURNING device_id;
        """
        # if the serial number already exists, we update the part number, station name, can port 
        # and can msg id to ensure the device information is up to date, and return the existing device id.
        with pgs_conn.cursor() as cursor:
            cursor.execute(query, (serial_number, partnumber, station_name, can_port, can_msg_id))
            device_id = cursor.fetchone()[0]
            pgs_conn.commit()
            
        redis_cache.set(cache_key, device_id)
        return device_id
    
    
# if __name__ == "__main__":
#     # for testing purpose, we can run this script independently to test the device id retrieval and caching functionality
#     pgs_conn = postgresql_connection_pool.getconn()
#     serial_number = "SN123456"
#     partnumber = "PN654321"
#     can_msg_id = 0x123
#     device_id = get_device_id_from_cache(pgs_conn, serial_number, partnumber, can_msg_id)
#     print(f"Device ID for serial number {serial_number} and part number {partnumber} is: {device_id}")