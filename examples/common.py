
def print_devices(b):
    for device in sorted(b.devices, key=lambda d: len(d.ancestors)):
        print(device)    # this is a blivet.devices.StorageDevice instance

    print()
