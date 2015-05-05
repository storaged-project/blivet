#!/usr/bin/python3

import sys

from pocketlint import FalsePositive, PocketLintConfig, PocketLinter

class BlivetLintConfig(PocketLintConfig):
    def __init__(self):
        PocketLintConfig.__init__(self)

        self.falsePositives = [ FalsePositive(r"BTRFSVolumeDevice._create: Instance of 'DeviceFormat' has no 'label' member"),
                                FalsePositive(r"Catching an exception which doesn't inherit from BaseException: (BlockDev|DM|Crypto|Swap|LVM|Btrfs|MDRaid|)Error$"),
                                FalsePositive(r"Function 'run_program' has no 'called' member"),
                                FalsePositive(r"(PartitioningTestCase|PartitionDeviceTestCase).*: Instance of 'DeviceFormat' has no .* member"),
                                FalsePositive(r"Instance of 'int' has no .* member"),
                                FalsePositive(r"Instance of 'LUKSDevice' has no .* member"),
                                FalsePositive(r"Method 'doTask' is abstract in class 'Task' but is not overridden"),
                                FalsePositive(r"Method 'doTask' is abstract in class 'UnimplementedTask' but is not overridden"),
                                FalsePositive(r"No value for argument 'member_count' in unbound method call$"),
                                FalsePositive(r"No value for argument 'smallest_member_size' in unbound method call$"),

                                # FIXME:  These are temporary, until there's a python3 anaconda.
                                FalsePositive(r"Unable to import 'pyanaconda'$"),
                                FalsePositive(r"Unable to import 'pyanaconda.*'$"),
                              ]

    @property
    def disabledOptions(self):
        return [ "W0105",           # String statement has no effect
                 "W0110",           # map/filter on lambda could be replaced by comprehension
                 "W0141",           # Used builtin function %r
                 "W0142",           # Used * or ** magic
                 "W0212",           # Access to a protected member of a client class
                 "W0511",           # Used when a warning note as FIXME or XXX is detected.
                 "W0603",           # Using the global statement
                 "W0614",           # Unused import %s from wildcard import
                 "I0011",           # Locally disabling %s
               ]

if __name__ == "__main__":
    conf = BlivetLintConfig()
    linter = PocketLinter(conf)
    rc = linter.run()
    sys.exit(rc)
