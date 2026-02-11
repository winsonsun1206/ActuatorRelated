import can
import time
import struct
from datetime import datetime

def send_keep_alive():
    # 1. Setup the CAN Bus (SocketCAN on Raspberry Pi)
    bus = can.interface.Bus(channel='can1', interface='socketcan')

    # 2. Define Command Parameters
    # Target ID: 3
    target_id = 0x03
    
    # Command: MCL_KEEP_ALIVE (Address 0x3F / 63)
    cmd_address = 0x3F
    
    # Key: 0x85FAC673 (Must be sent Little-Endian: 73 C6 FA 85)
    # We use struct.pack('<I', ...) to ensure it is Little-Endian unsigned int
    key_value = 0x85FAC673
    key_bytes = list(struct.pack('<I', key_value)) # Result: [0x73, 0xC6, 0xFA, 0x85]

    # Datatype: U32 (0x00)
    data_type = 0x00

    # 3. Construct the 8-Byte Payload
    # Byte 0: Address
    # Byte 1-4: Data (Key)
    # Byte 5: Type
    # Byte 6-7: Reserved (0x00)
    payload = [cmd_address] + key_bytes + [data_type, 0x00, 0x00]
    
    # Final Payload Check: [0x3F, 0x73, 0xC6, 0xFA, 0x85, 0x00, 0x00, 0x00]

    # 4. Create the Message Object
    msg = can.Message(
        arbitration_id=target_id,
        data=payload,
        is_extended_id=False
    )

    print(f"Starting Keep Alive Loop for ID {target_id}...")
    
    try:
        while True:
            bus.send(msg)
            # Protocol timeout is 3000ms. Sending every 1.0s is safe.
            time.sleep(1.0) 
            print(f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')}:Heartbeat sent.{msg.data}")
            
    except KeyboardInterrupt:
        print("\nStopped.")

if __name__ == "__main__":
    send_keep_alive()