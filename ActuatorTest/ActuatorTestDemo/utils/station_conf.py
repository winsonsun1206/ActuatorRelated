
import os

"""
samples of station_conf.txt:
station_name: station_1
"""
station_config = "~/station_conf.txt"

def read_station_conf():
    with open(os.path.expanduser(station_config), "r") as f:
        lines = f.readlines()
        conf = {}
        for line in lines:
            key, value = line.strip().split(":")
            conf[key] = value
    return conf