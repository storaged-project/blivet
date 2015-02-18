
def print_devices(b):
    print
    for device in sorted(b.devices, key=lambda d: len(d.ancestors)):
        print device
        if device.fstabSpec and device.fstabSpec != device.path:
            print "\t", device.fstabSpec
        if device.uuid:
            print "\t", device.uuid

    print
