import redis
import json

class RedisHandler:
    def __init__(self, host='localhost', port=6379, db=0):
        self.redis_client = redis.Redis(host=host, port=port, db=db)

    def set_value(self, key, value):
        # set retention time to 24 hours (86400 seconds)
        self.redis_client.setex(key, 86400, json.dumps(value))
    
    def get_value(self, key):
        value = self.redis_client.get(key)
        if value is not None:
            return json.loads(value)
        return None

    def delete_value(self, key):
        self.redis_client.delete(key)

    def flush_db(self):
        """Flush the entire Redis database."""
        self.redis_client.flushdb()

    def get_all_keys_and_values(self):
        """Get a list of all keys in the Redis database."""
        return {key.decode('utf-8'): json.loads(self.redis_client.get(key)) for key in self.redis_client.keys()}
    
    def key_exists(self, key):
        """Check if a specific key exists in the Redis database."""
        return self.redis_client.exists(key) > 0
    
    def delete_keys_by_pattern(self, pattern):
        """Delete keys matching a specific pattern."""
        keys_to_delete = self.redis_client.keys(pattern)
        if keys_to_delete:
            self.redis_client.delete(*keys_to_delete)

    def delete_all_keys(self):
        """Delete all keys in the Redis database."""
        self.redis_client.flushdb()


if __name__ == "__main__":
    redis_handler = RedisHandler(host='192.168.2.47', port=6379, db=0)
    #redis_handler.flush_db()  # Clear the database before testing
    # test_data = 22
    # redis_handler.set_value("station_1_can0_bus_1_sadsada_calibration", test_data)
 
    
    print(redis_handler.get_all_keys_and_values())