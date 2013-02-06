import logging
import sys

blivet_log = logging.getLogger("blivet")

def set_up_logging():
    """ Configure the blivet logger to use /tmp/blivet.log as its log file. """
    blivet_log.setLevel(logging.DEBUG)
    program_log = logging.getLogger("program")
    program_log.setLevel(logging.DEBUG)
    handler = logging.FileHandler("/tmp/blivet.log")
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s,%(msecs)03d %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    blivet_log.addHandler(handler)
    program_log.addHandler(handler)


# doing this before importing blivet gets the logging from format class
# registrations and other stuff triggered by the import
set_up_logging()

import blivet

blivet_log.info(sys.argv[0])

storage = blivet.Blivet()   # create an instance of Blivet
storage.reset()             # detect system storage configuration

for device in sorted(storage.devices, key=lambda d: len(d.ancestors)):
    print device    # this is a blivet.devices.StorageDevice instance

