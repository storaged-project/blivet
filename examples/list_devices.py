import logging
import sys

from common import set_up_logging
from common import print_devices

# doing this before importing blivet gets the logging from format class
# registrations and other stuff triggered by the import
set_up_logging()
blivet_log = logging.getLogger("blivet")
blivet_log.info(sys.argv[0])

import blivet

storage = blivet.Blivet()   # create an instance of Blivet
storage.reset()             # detect system storage configuration

print_devices(b)
