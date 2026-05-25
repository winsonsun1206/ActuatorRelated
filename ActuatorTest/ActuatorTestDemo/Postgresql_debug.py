from utils.device_id import get_device_id_from_cache
from utils.pqs_handler import postgresql_connection_pool

def test_get_device_id_from_cache():
    serial_numbers = ["rp", "po", "ll"]
    part_numbers = ["1566", "1566", "1566"]
    can_msg_addresses = [1, 2, 3]
    device_ids = [get_device_id_from_cache(postgresql_connection_pool.getconn(), serial_number, part_number, can_msg_id) for serial_number, part_number, can_msg_id in zip(serial_numbers, part_numbers, can_msg_addresses)]
    return device_ids
    
if __name__ == "__main__":
    print(test_get_device_id_from_cache())