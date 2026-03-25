import can

def shutdown_can_interface(channel):
    try:
        bus = can.interface.Bus(channel=channel, bustype='socketcan')
        bus.shutdown()
        print(f"CAN interface {channel} has been shut down successfully.")
    except Exception as e:
        print(f"Error shutting down CAN interface {channel}: {e}")


if __name__ == "__main__":
    can_channel = 'can0'  # 替换为你的CAN接口名称
    shutdown_can_interface(can_channel)
    can_channel = 'can1'  # 替换为你的CAN接口名称
    shutdown_can_interface(can_channel)