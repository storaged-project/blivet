import time

from examples.common import print_devices

import blivet
from blivet.events.manager import event_manager
from blivet.util import set_up_logging


def print_changes(event, changes):
    print("***", event)
    for change in changes:
        print("***", change)
    print("***")
    print()

set_up_logging(console_logs=["blivet.event"])
b = blivet.Blivet()  # create an instance of Blivet
b.reset()  # detect system storage configuration
print_devices(b)

event_manager.notify_cb = print_changes
event_manager.enable()

while True:
    time.sleep(0.5)
