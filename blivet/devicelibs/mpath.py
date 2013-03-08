
from .. import util

import logging
log = logging.getLogger("blivet")

def flush_mpaths():
    util.run_program(["multipath", "-F"])
    check_output = util.capture_output(["multipath", "-ll"]).strip()
    if check_output:
        log.error("multipath: some devices could not be flushed")

def is_multipath_member(path):
    return (util.run_program(["multipath", "-c", path]) == 0)
