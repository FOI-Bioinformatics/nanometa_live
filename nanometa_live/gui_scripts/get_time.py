"""
Returns the current time.

"""

import time

def get_time():
    t = time.localtime()
    current_time = time.strftime("%H:%M:%S", t)
    return current_time