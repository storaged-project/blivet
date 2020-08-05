
import dbus

bus = dbus.SystemBus()

# This adds a signal match so that the client gets signals sent by Blivet1's
# ObjectManager. These signals are used to notify clients of changes to the
# managed objects (for blivet, this will be devices, formats, and actions).
bus.add_match_string("type='signal',sender='com.redhat.Blivet1',path_namespace='/com/redhat/Blivet1'")

blivet = bus.get_object('com.redhat.Blivet1', '/com/redhat/Blivet1/Blivet')
blivet.Reset()

object_manager = bus.get_object('com.redhat.Blivet1', '/com/redhat/Blivet1')
objects = object_manager.GetManagedObjects()
for object_path in blivet.ListDevices():
    device = objects[object_path]['com.redhat.Blivet1.Device']
    fmt = objects[device['Format']]['com.redhat.Blivet1.Format']
    print(device['Name'], device['Type'], device['Size'], fmt['Type'])
