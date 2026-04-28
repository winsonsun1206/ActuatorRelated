import redis
import psycopg2
import dotenv
import os

    
dotenv.load_dotenv(dotenv_path= os.path.join(os.path.dirname(__file__), '../secrets/.env'))

redis_cache = redis.Redis(
    host=os.getenv("REDIS_HOST"),
    port=int(os.getenv("REDIS_PORT")),
    db=int(os.getenv("REDIS_DB_DEVICE_ID_CACHE")), decode_responses=True
)

def get_device_id_from_cache(pgs_conn, serial_number, partnumber, can_msg_id):
    # fast check the redis cache and return the device id if found, otherwise query the postgresql database and update the cache
    cache_key = f"{serial_number}_{partnumber}"
    device_id = redis_cache.get(cache_key)
    if device_id is not None:
        return int(device_id)
    else:
        query = """
        INSERT INTO devices (serial_number, part_number, can_msg_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (serial_number) DO UPDATE SET part_number = EXCLUDED.part_number
        RETURNING device_id;
        """
        # if the serial number already exists, update the part number and return the device id, 
        # otherwise insert a new record and return the new device id  
        # the device id is created automatically by the database as a primary key with auto-increment, so we can get the device id by executing the query and fetching the result
        
        with pgs_conn.cursor() as cursor:
            cursor.execute(query, (serial_number, partnumber, can_msg_id))
            device_id = cursor.fetchone()[0]
            pgs_conn.commit()
            
        redis_cache.set(cache_key, device_id)
        return device_id