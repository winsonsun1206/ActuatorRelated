from datetime import datetime, timedelta
import time

from utils.send_data import send_can_data

start_timestamp = datetime.now()
heartbeat_command = b'\x3F\x73\xC6\xFA\x85\x00\x00\x00' 
while datetime.now()- start_timestamp <timedelta(seconds=360):
    send_can_data("can0", [1], heartbeat_command)
    time.sleep(1)
    
    