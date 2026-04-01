
import os
from pathlib import Path
"""
samples of station_conf.txt:
station_name: station_1
"""
station_config = str(Path.home() / "station_conf.txt")

def read_station_conf():
    with open(station_config, "r") as f:
        lines = f.readlines()
        conf = {}
        for line in lines:
            key, value = line.strip().split(":")
            conf[key] = value
    return conf.strip()