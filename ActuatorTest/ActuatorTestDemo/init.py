import os
import can
import time

def initialize_can_interface():
    os.system('sudo ip link set can1 type can bitrate 1000000')
    os.system('sudo ifconfig can1 txqueuelen 65536')
    os.system('sudo ifconfig can1 up')
    os.system('sudo ip link set can0 type can bitrate 1000000')
    os.system('sudo ifconfig can0 txqueuelen 65536')
    os.system('sudo ifconfig can0 up')
    return None


if __name__ == "__main__":
    initialize_can_interface()