import blivet
from blivet.util import set_up_logging

set_up_logging()
b = blivet.Blivet()   # create an instance of Blivet
b.reset()             # detect system storage configuration

print(b.devicetree)
