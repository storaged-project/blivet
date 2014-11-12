
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

def set_friendly_names(enabled=True):
    """ Set the state of friendly names in multipathd.

        NOTE: If you call this you also need to take appropriate steps to make
              sure the devicetree contains devices with the appropriate names.
              They will not be updated automatically.
    """
    if enabled:
        val = "y"
    else:
        val = "n"

    # --find_multipaths is important to keep multipath from making up multipath devices
    # that aren't really multipath
    cmd = ["mpathconf", "--find_multipaths", "y", "--user_friendly_names", val, "--with_multipathd", "y"]
    return (util.run_program(cmd) == 0)
