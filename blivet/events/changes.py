# events/changes.py
# Per-thread change accounting data structures.
#
# Copyright (C) 2016  Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU Lesser General Public License v.2, or (at your option) any later
# version. This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY expressed or implied, including the implied
# warranties of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See
# the GNU Lesser General Public License for more details.  You should have
# received a copy of the GNU Lesser General Public License along with this
# program; if not, write to the Free Software Foundation, Inc., 51 Franklin
# Street, Fifth Floor, Boston, MA 02110-1301, USA.  Any Red Hat trademarks
# that are incorporated in the source code or documentation are not subject
# to the GNU Lesser General Public License and may only be used or
# replicated with the express permission of Red Hat, Inc.
#
# Red Hat Author(s): David Lehman <dlehman@redhat.com>
#

from threading import local

from ..callbacks import callbacks
from .. import util


data = local()
""" Thread-local data for event handler threads. """

data.changes = list()  # Saves checking if the list exists in the main thread.


""" Accounting for changes made in response to an event.

    We want to end up with a single, ordered list containing every change
    that was made in response to a specific event.
"""
_DeviceAdded = util.default_namedtuple("DeviceAdded", ["device"])
_DeviceRemoved = util.default_namedtuple("DeviceRemoved", ["device"])
_ActionCanceled = util.default_namedtuple("ActionCanceled", ["action"])
_ParentAdded = util.default_namedtuple("ListItemAdded", ["device", "item"])
_ParentRemoved = util.default_namedtuple("ListItemRemoved", ["device", "item"])
_AttributeChanged = util.default_namedtuple("AttrChanged", ["device", ("fmt", None), "attr", "old", "new"])


class DeviceAdded(_DeviceAdded):
    def __str__(self):
        return "add device '%s'" % str(self.device)


class DeviceRemoved(_DeviceRemoved):
    def __str__(self):
        return "remove device %s" % self.device.name


class ActionCanceled(_ActionCanceled):
    def __str__(self):
        return "cancel action '%s'" % str(self.action)


class ParentAdded(_ParentAdded):
    def __str__(self):
        return "add parent %s to %s" % (self.item.name, self.device.name)


class ParentRemoved(_ParentRemoved):
    def __str__(self):
        return "remove parent %s from %s" % (self.item.name, self.device.name)


class AttributeChanged(_AttributeChanged):
    def __str__(self):
        return "change attribute %s of %s%s from '%s' to '%s'" % (self.attr,
                                                                  self.device.name,
                                                                  " format" if self.fmt else "",
                                                                  str(self.old),
                                                                  str(self.new))


def record_change(change):
    if not hasattr(data, "changes"):
        data.changes = list()

    data.changes.append(change)


def device_added_cb(device):
    record_change(DeviceAdded(device))


def device_removed_cb(device):
    record_change(DeviceRemoved(device))


def action_removed_cb(action):
    record_change(ActionCanceled(action))


def parent_added_cb(device, parent):
    record_change(ParentAdded(parent, device))


def parent_removed_cb(device, parent):
    record_change(ParentRemoved(parent, device))


def attribute_changed_cb(device, attr, old, new, fmt=None):
    record_change(AttributeChanged(device, fmt, attr, old, new))


def _control_callbacks(meth):
    getattr(callbacks.device_added, meth)(device_added_cb)
    getattr(callbacks.device_removed, meth)(device_removed_cb)
    getattr(callbacks.action_removed, meth)(action_removed_cb)
    getattr(callbacks.parent_added, meth)(parent_added_cb)
    getattr(callbacks.parent_removed, meth)(parent_removed_cb)
    getattr(callbacks.attribute_changed, meth)(attribute_changed_cb)


def enable_callbacks():
    _control_callbacks("add")


def disable_callbacks():
    _control_callbacks("remove")
