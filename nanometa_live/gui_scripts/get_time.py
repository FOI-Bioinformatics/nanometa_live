import time

def get_time():
    """
    Returns the current time.
    """
    t = time.localtime()
    current_time = time.strftime("%H:%M:%S", t)
    return current_time
